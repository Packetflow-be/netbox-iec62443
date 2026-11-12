"""Connection models (#11): reverse connect, flows through a broker, connectionless publish."""
from django.core.exceptions import ValidationError
from django.test import TestCase

from dcim.models import Site
from ipam.models import Prefix

from netbox_iec62443.accessmap import access_map_flows, access_map_svg, attention
from netbox_iec62443.checks import run_checks
from netbox_iec62443.filtersets import FlowFilterSet
from netbox_iec62443.models import Conduit, Flow, Zone
from netbox_iec62443.rules import build_rules


class ConnectionTestBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(name='Plant', slug='plant')
        cls.cell = Zone.objects.create(name='Cell', slug='cell', site=cls.site, purdue_level='1')
        cls.dmz = Zone.objects.create(name='DMZ', slug='dmz', site=cls.site, purdue_level='3.5', zone_type='dmz')
        cls.office = Zone.objects.create(name='Office', slug='office', site=cls.site, purdue_level='4',
                                         zone_type='enterprise')
        for zone, cidr in ((cls.cell, '10.1.1.0/24'), (cls.dmz, '10.1.35.0/24'), (cls.office, '10.1.4.0/24')):
            zone.prefixes.add(Prefix.objects.create(prefix=cidr, scope=cls.site))
        cls.reverse = Flow.objects.create(
            name='MES', source_zone=cls.dmz, destination_zone=cls.cell, protocol='opc-ua',
            port_mappings=['tcp/4843'], access=['read', 'write'], connection='reverse-connect', allowed='yes',
        )
        cls.brokered = Flow.objects.create(
            name='Recipes', source_zone=cls.office, destination_zone=cls.cell, protocol='mqtt',
            port_mappings=['tcp/8883'], access=['write'], connection='brokered', broker_zone=cls.dmz,
            topics=['spBv1.0/line1/DCMD/gw-1'], allowed='yes',
        )
        cls.direct = Flow.objects.create(
            name='HMI', source_zone=cls.office, destination_zone=cls.cell, protocol='s7comm',
            port_mappings=['tcp/102'], access=['read'], allowed='yes',
        )


class ConnectionModelTest(ConnectionTestBase):

    def test_broker_zone_goes_with_brokered(self):
        flow = Flow(source_zone=self.office, destination_zone=self.cell, connection='brokered')
        with self.assertRaisesRegex(ValidationError, 'zone of the broker'):
            flow.full_clean()
        flow = Flow(source_zone=self.office, destination_zone=self.cell, broker_zone=self.dmz)
        with self.assertRaisesRegex(ValidationError, 'Only a flow through a broker'):
            flow.full_clean()

    def test_conduit_joins_the_broker_zone(self):
        conduit = Conduit.objects.create(name='Office - Cell', site=self.site)
        conduit.zones.set([self.office, self.cell])
        self.brokered.conduit = conduit
        with self.assertRaisesRegex(ValidationError, 'broker zone'):
            self.brokered.full_clean()
        conduit.zones.add(self.dmz)
        self.brokered.full_clean()

    def test_transport_legs(self):
        self.assertEqual(self.direct.transport_legs, [(self.office, self.cell)])
        self.assertEqual(self.reverse.transport_legs, [(self.cell, self.dmz)])
        self.assertEqual(self.brokered.transport_legs, [(self.office, self.dmz), (self.cell, self.dmz)])
        local = Flow(source_zone=self.dmz, destination_zone=self.cell, connection='brokered', broker_zone=self.dmz)
        self.assertEqual(local.transport_legs, [(self.cell, self.dmz)])
        self.assertTrue(self.reverse.is_outbound_only)
        self.assertFalse(self.direct.is_outbound_only)


class ConnectionRulesTest(ConnectionTestBase):

    def _rules(self, flow):
        rules, _skipped = build_rules(Flow.objects.filter(pk=flow.pk))
        return rules

    def test_reverse_connect_is_opened_by_the_destination(self):
        [rule] = self._rules(self.reverse)
        self.assertEqual((rule['source_zone'], rule['destination_zone']), ('Cell', 'DMZ'))
        self.assertEqual((rule['source_networks'], rule['destination_networks']), ('10.1.1.0/24', '10.1.35.0/24'))
        self.assertEqual(rule['ports'], '4843')
        self.assertEqual(rule['connection'], 'Reverse connect')
        self.assertIn('reverse connect', rule['notes'])

    def test_brokered_is_two_rules_into_the_broker_zone(self):
        rules = self._rules(self.brokered)
        self.assertEqual([(r['rule'], r['source_zone'], r['destination_zone']) for r in rules], [
            (f'{self.brokered.pk}-pub', 'Office', 'DMZ'),
            (f'{self.brokered.pk}-sub', 'Cell', 'DMZ'),
        ])
        self.assertTrue(all(r['ports'] == '8883' for r in rules))

    def test_client_server_unchanged(self):
        [rule] = self._rules(self.direct)
        self.assertEqual((rule['rule'], rule['source_zone'], rule['destination_zone']),
                         (str(self.direct.pk), 'Office', 'Cell'))
        self.assertEqual(rule['connection'], 'Client/server')


class ConnectionFilterTest(ConnectionTestBase):

    def _names(self, params):
        return sorted(FlowFilterSet(params, Flow.objects.all()).qs.values_list('name', flat=True))

    def test_filters(self):
        self.assertEqual(self._names({'connection': ['brokered']}), ['Recipes'])
        self.assertEqual(self._names({'outbound_only': 'true'}), ['MES', 'Recipes'])
        self.assertEqual(self._names({'outbound_only': 'false'}), ['HMI'])
        self.assertEqual(self._names({'broker_zone_id': [self.dmz.pk]}), ['Recipes'])
        self.assertEqual(self._names({'topics': 'dcmd'}), ['Recipes'])
        self.assertEqual(self._names({'q': 'line1/DCMD'}), ['Recipes'])
        # A flow through a broker counts for the broker's zone too
        self.assertEqual(self._names({'zone_id': [self.dmz.pk]}), ['MES', 'Recipes'])


class ConnectionAccessMapTest(ConnectionTestBase):

    def test_outbound_only_needs_attention(self):
        self.assertEqual(attention(Flow.objects.all())['outbound_only'], 2)

    def test_dotted_arrows_and_titles(self):
        flows = list(access_map_flows(site=self.site, max_level='2'))
        self.assertEqual(len(flows), 3)
        svg = access_map_svg(flows)
        self.assertIn('stroke-dasharray="2 4"', svg)  # DMZ -> Cell: reverse connect only
        self.assertIn('through a broker in DMZ', svg)

    def test_brokered_write_without_topics(self):
        self.assertFalse([f for f in run_checks(site=self.site) if f.check == 'brokered-write-without-topics'])
        Flow.objects.filter(pk=self.brokered.pk).update(topics=[])
        found = [f for f in run_checks(site=self.site) if f.check == 'brokered-write-without-topics']
        self.assertEqual([f.obj.pk for f in found], [self.brokered.pk])
