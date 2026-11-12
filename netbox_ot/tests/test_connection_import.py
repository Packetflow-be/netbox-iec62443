"""Importing connection models (#11): OPC UA Reverse Connect and MQTT through a broker, from Zeek logs and files."""
from django.test import SimpleTestCase, TestCase

from dcim.models import Site

from netbox_ot.importers import zeek
from netbox_ot.importers.observations import apply_plan, build_plan
from netbox_ot.models import Flow, Zone

T0 = 1793520000  # 2026-11-01T08:00:00Z
PLC, GATEWAY, HMI, MES, BROKER, OFFICE = (
    '10.10.10.10', '10.10.10.20', '10.10.20.5', '10.10.35.5', '10.10.35.9', '10.10.40.5',
)
ZONES = zeek.ZoneMap(networks={
    '10.10.10.0/24': 'Cell', '10.10.20.0/24': 'Control', '10.10.35.0/24': 'DMZ', '10.10.40.0/24': 'Office',
}, levels={'Cell': '1', 'Control': '2', 'DMZ': '3.5', 'Office': '4'})


def conn(uid, orig, resp, port, ts=T0):
    return {'ts': ts, 'uid': uid, 'id.orig_h': orig, 'id.resp_h': resp, 'id.resp_p': str(port)}


LOGS = {
    # The PLC opens the connection to the MES (ReverseHello), then the MES reads and writes over it
    'opcua_binary': [
        {**conn('R1', PLC, MES, 4843), 'msg_type': 'RHE'},
        {**conn('R1', PLC, MES, 4843), 'msg_type': 'HEL'},
        {**conn('R1', PLC, MES, 4843), 'msg_type': 'MSG', 'req_identifier_str': 'ReadRequest'},
        {**conn('R1', PLC, MES, 4843), 'msg_type': 'MSG', 'req_identifier_str': 'WriteRequest'},
        # An ordinary client/server session next to it
        {**conn('O1', HMI, PLC, 4840), 'msg_type': 'MSG', 'req_identifier_str': 'ReadRequest'},
    ],
    'mqtt_publish': [
        # The office dashboard publishes a Sparkplug command twice; the gateway gets it through the broker
        {**conn('M1', OFFICE, BROKER, 1883, T0 + 10), 'from_client': 'T', 'topic': 'spBv1.0/line1/DCMD/gw'},
        {**conn('M1', OFFICE, BROKER, 1883, T0 + 20), 'from_client': 'T', 'topic': 'spBv1.0/line1/DCMD/gw'},
        # The gateway publishes data, which the broker delivers to the HMI (no subscribe record seen)
        {**conn('M2', GATEWAY, BROKER, 1883, T0 + 30), 'from_client': True, 'topic': 'plant/line1/temp'},
        {**conn('M3', HMI, BROKER, 1883, T0 + 31), 'from_client': False, 'topic': 'plant/line1/temp'},
    ],
    'mqtt_subscribe': [
        {**conn('M2', GATEWAY, BROKER, 1883), 'action': 'MQTT::SUBSCRIBE', 'topics': ['spBv1.0/line1/DCMD/#']},
        {**conn('M1', OFFICE, BROKER, 1883), 'action': 'MQTT::UNSUBSCRIBE', 'topics': 'plant/#'},
    ],
}


class TopicMatchTest(SimpleTestCase):

    def test_wildcards(self):
        cases = [
            ('a/b/c', 'a/b/c', True), ('a/+/c', 'a/b/c', True), ('a/#', 'a/b/c', True), ('a/#', 'a', True),
            ('#', 'a/b', True), ('a/+', 'a/b/c', False), ('a/b', 'a/b/c', False), ('a/b/c/d', 'a/b/c', False),
            ('spBv1.0/line1/DCMD/#', 'spBv1.0/line1/DCMD/gw', True), ('a/#/c', 'a/b/c', False),
        ]
        for topic_filter, topic, expected in cases:
            with self.subTest(topic_filter=topic_filter, topic=topic):
                self.assertEqual(zeek.topic_matches(topic_filter, topic), expected)


class ZeekConnectionTest(SimpleTestCase):

    def setUp(self):
        self.assets, self.flows, _summary = zeek.to_observations(LOGS, ZONES)

    def _flows(self, **match):
        return [f for f in self.flows if all(f.get(k) == v for k, v in match.items())]

    def test_reverse_connect_turned_round(self):
        reverse = self._flows(connection='reverse-connect')
        self.assertEqual({(f['src'], f['dst'], f['port']) for f in reverse}, {(MES, PLC, 4843)})
        self.assertIn('WriteRequest', {f.get('func') for f in reverse})
        self.assertFalse(self._flows(src=PLC, dst=MES))
        # The ordinary session is untouched
        self.assertEqual(self._flows(src=HMI, dst=PLC)[0].get('connection'), None)

    def test_mqtt_through_the_broker(self):
        command = self._flows(src=OFFICE, dst=GATEWAY)
        self.assertEqual(len(command), 1)
        self.assertEqual(command[0], {**command[0], 'proto': 'mqtt', 'connection': 'brokered', 'broker': BROKER,
                                      'topic': 'spBv1.0/line1/DCMD/gw', 'port': 1883, 'access': 'write',
                                      'count': 2, 'func': 'PUBLISH'})
        data = self._flows(src=GATEWAY, dst=HMI)
        self.assertEqual([(f['topic'], f.get('access')) for f in data], [('plant/line1/temp', None)])
        # Nobody else subscribed to the office's topic; the unsubscribe is ignored
        self.assertFalse(self._flows(dst=OFFICE))
        self.assertIn(BROKER, {a['ip'] for a in self.assets})


class PlanConnectionTest(SimpleTestCase):

    def test_plan(self):
        assets, flows, summary = zeek.to_observations(LOGS, ZONES)
        plan = build_plan(assets, flows, summary)
        by_name = {f.name: f for f in plan.flows}
        brokered = by_name['Office -> Cell MQTT via broker in DMZ']
        self.assertEqual((brokered.connection, brokered.broker_zone, brokered.topics, brokered.access,
                          brokered.port_mappings), ('brokered', 'DMZ', ['spBv1.0/line1/DCMD/gw'], ['write'],
                                                    ['tcp/1883']))
        self.assertIn('Through the broker 10.10.35.9 in DMZ', brokered.evidence)
        reverse = by_name['DMZ -> Cell OPC UA (reverse connect)']
        self.assertEqual((reverse.connection, reverse.port_mappings), ('reverse-connect', ['tcp/4843']))
        roles = {(s.ip, s.protocol, s.role): s.port_mappings for s in plan.services}
        self.assertEqual(roles[(BROKER, 'mqtt', 'server')], ['tcp/1883'])
        self.assertIn((OFFICE, 'mqtt', 'publisher'), roles)
        self.assertIn((GATEWAY, 'mqtt', 'subscriber'), roles)
        # The OPC UA server in a reverse connect does not get the client's listening port
        self.assertEqual(roles[(PLC, 'opc-ua', 'server')], ['tcp/4840'])
        self.assertIn(BROKER, plan.hosts[OFFICE].peers)
        self.assertNotIn(GATEWAY, plan.hosts[OFFICE].peers)

    def test_validation(self):
        asset = [{'ip': PLC, 'zone': 'Cell'}]
        for flow, message in (
            ({'src': OFFICE, 'dst': PLC, 'proto': 'mqtt', 'connection': 'brokered'}, 'broker'),
            ({'src': OFFICE, 'dst': PLC, 'proto': 'mqtt', 'broker': BROKER}, 'brokered'),
            ({'src': OFFICE, 'dst': PLC, 'proto': 'mqtt', 'connection': 'sideways'}, 'connection is one of'),
        ):
            with self.subTest(flow=flow), self.assertRaisesRegex(ValueError, message):
                build_plan(asset, [flow], {})


class ApplyConnectionTest(TestCase):

    def test_apply_and_rerun(self):
        site = Site.objects.create(name='Plant', slug='plant')
        assets, flows, summary = zeek.to_observations(LOGS, ZONES)
        apply_plan(build_plan(assets, flows, summary), site, log=lambda m: None)
        brokered = Flow.objects.get(connection='brokered', source_zone__name='Office')
        self.assertEqual((brokered.broker_zone.name, brokered.destination_zone.name, brokered.topics),
                         ('DMZ', 'Cell', ['spBv1.0/line1/DCMD/gw']))
        reverse = Flow.objects.get(connection='reverse-connect')
        self.assertEqual((reverse.source_zone.name, reverse.destination_zone.name), ('DMZ', 'Cell'))
        # The clients' own connections to the broker are not in LOGS (no conn.log), so no client/server MQTT flows
        self.assertFalse(Flow.objects.filter(protocol='mqtt', connection='client-server').exists())

        # A second capture with another topic adds it to the same flow
        more = [dict(f) for f in flows]
        for f in more:
            if f.get('topic') == 'spBv1.0/line1/DCMD/gw':
                f['topic'] = 'spBv1.0/line1/NCMD/gw'
        apply_plan(build_plan(assets, more, summary), site, log=lambda m: None)
        brokered.refresh_from_db()
        self.assertEqual(brokered.topics, ['spBv1.0/line1/DCMD/gw', 'spBv1.0/line1/NCMD/gw'])
        self.assertEqual(Flow.objects.filter(connection='brokered', source_zone__name='Office').count(), 1)
        self.assertEqual(Zone.objects.filter(site=site).count(), 4)
