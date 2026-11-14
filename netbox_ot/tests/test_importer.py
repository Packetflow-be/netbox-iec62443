import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from dcim.models import Interface, Region, Site
from ipam.models import VRF, IPAddress, Prefix, Service
from utilities.testing import create_test_device

from netbox_ot.customfields import PURDUE_CF_NAME
from netbox_ot.importers import functions
from netbox_ot.importers.observations import apply_plan, build_plan
from netbox_ot.models import Conduit, Flow, IndustrialService, Zone

# A small set of observation files (docs/import-format.md), documentation addresses, no real site
ASSETS = [
    {'ip': '10.10.10.10', 'role': 'PLC', 'purdue_level': 1, 'zone': 'Z1 Cell A', 'open_ports': [102, 502]},
    {'ip': '10.10.10.20', 'role': 'HMI', 'purdue_level': 2, 'zone': 'Z1 Cell A'},
    {'ip': '192.168.1.10', 'role': 'Supplier 4G gateway', 'purdue_level': 3, 'zone': 'Z4 External',
     'remote_access': True},
    {'ip': '192.168.2.42', 'role': 'Laptop', 'purdue_level': 4, 'zone': 'Z5 Office'},
]
FLOWS = [
    {'src': '10.10.10.20', 'dst': '10.10.10.10', 'proto': 'S7comm', 'func': 'Read Variable', 'count': 500},
    {'src': '192.168.1.10', 'dst': '10.10.10.10', 'proto': 'S7comm', 'func': 'Write Variable', 'count': 12},
    {'src': '192.168.1.10', 'dst': '10.10.10.10', 'proto': 'S7comm', 'func': 'Read Variable', 'count': 12},
]
SUMMARY = {
    'captures': ['cap1'], 'hours': 2.0,
    'zone_pairs': [
        {'from': 'Z4 External', 'to': 'Z1 Cell A', 'count': 12},
        {'from': 'Z5 Office', 'to': 'Z1 Cell A', 'count': 300},
        {'from': 'Z5 Office', 'to': 'Elsewhere', 'count': 40},
    ],
}
CONTROL, SUPERVISORY = 'Z1 Cell A (control)', 'Z1 Cell A (supervisory)'


class ClassifyTest(SimpleTestCase):

    def test_explicit_tables(self):
        cases = [
            ('modbus-tcp', 'Read Holding Registers', functions.READ),
            ('modbus-tcp', 'WRITE_MULTIPLE_REGISTERS', functions.WRITE),
            ('modbus-tcp', 'Force Single Coil', functions.WRITE),  # Modicon name, no "Write" in it
            ('modbus-tcp', 'Preset Multiple Registers', functions.WRITE),
            ('modbus-tcp', '16', functions.WRITE),
            ('modbus-tcp', 'Read/Write Multiple Registers', functions.WRITE),
            ('s7comm', 'PLC Stop', functions.CONTROL),
            ('s7comm', 'Request download', functions.PROGRAM),
            ('s7comm', 'DOWNLOAD_BLOCK', functions.PROGRAM),
            ('s7comm', 'Start upload', functions.READ),
            ('dnp3', 'DIRECT_OPERATE', functions.CONTROL),
            ('dnp3', 'COLD_RESTART', functions.CONTROL),
            ('ethernet-ip', 'Write_Tag', functions.WRITE),
            ('ethernet-ip', 'Stop', functions.CONTROL),
            ('iec-104', 'C_SC_NA_1', functions.CONTROL),
            ('iec-104', 'C_SE_NC_1', functions.WRITE),
            ('iec-104', 'C_IC_NA_1', functions.READ),
            ('iec-104', 'M_ME_NC_1', functions.READ),
            ('iec-61850-mms', 'write', functions.WRITE),
            ('iec-61850-mms', 'initiateDownloadSequence', functions.PROGRAM),
            ('opc-ua', 'CallRequest', functions.CONTROL),
            ('opc-ua', 'ReadRequest', functions.READ),
            ('bacnet-ip', 'reinitialize-device', functions.CONTROL),
            ('omron-fins', 'Program Area Write', functions.PROGRAM),
        ]
        for protocol, func, expected in cases:
            with self.subTest(protocol=protocol, func=func):
                self.assertEqual(functions.classify(protocol, func), expected)

    def test_no_substring_guessing(self):
        # Unknown names stay unclassified rather than being guessed from a word in them
        self.assertEqual(functions.classify('s7comm', 'Rewrite cache'), functions.UNCLASSIFIED)
        self.assertEqual(functions.classify('modbus-tcp', 'Vendor Write Thing'), functions.UNCLASSIFIED)
        self.assertEqual(functions.classify(None, 'Write'), functions.UNCLASSIFIED)
        self.assertEqual(functions.classify('modbus-tcp', ''), functions.UNCLASSIFIED)


class BuildPlanTest(SimpleTestCase):

    def _flows(self, plan):
        return {(f.source, f.destination, f.protocol): f for f in plan.flows}

    def test_plan_splits_mixed_zone(self):
        plan = build_plan(ASSETS, FLOWS, SUMMARY, split_zones=['Z1 Cell A'])
        self.assertEqual(set(plan.zones), {CONTROL, SUPERVISORY, 'Z4 External', 'Z5 Office', 'Outside'})
        self.assertEqual(plan.zones[CONTROL].member_ips, ['10.10.10.10'])
        self.assertEqual(plan.zones[CONTROL].purdue_level, '1')
        self.assertEqual(plan.zones[SUPERVISORY].purdue_level, '2')
        self.assertEqual(plan.zones['Outside'].purdue_level, '')
        self.assertEqual(plan.zones['Outside'].zone_type, 'external')
        self.assertEqual(plan.zones['Z5 Office'].zone_type, 'enterprise')
        self.assertEqual(plan.zones[CONTROL].zone_type, 'ot')
        flows = self._flows(plan)
        self.assertEqual(set(flows), {
            ('Z4 External', CONTROL, 's7comm'),  # pinned to the PLC by its OT requests
            ('Z5 Office', CONTROL, ''),  # no OT requests: the most critical part, protocol unidentified
            ('Z5 Office', 'Outside', ''),
            (SUPERVISORY, CONTROL, 's7comm'),  # inside the old zone, now a flow
        })
        remote = flows[('Z4 External', CONTROL, 's7comm')]
        self.assertEqual(remote.name, 'Z4 External -> Z1 Cell A (control) S7comm')
        self.assertTrue(remote.remote_access)
        self.assertEqual(remote.access, ['read', 'write'])
        self.assertEqual(remote.port_mappings, [])  # the input gave no port, none is assumed
        self.assertIn('Write Variable x12 [write]', remote.evidence)
        self.assertIn('Changes the destination (write/control/program): Supplier 4G gateway (192.168.1.10)',
                      remote.evidence)
        # The flow's own count first, the zone pair's total (all protocols) as a labelled second line
        self.assertTrue(remote.evidence.startswith('Passively seen: 24 request(s) on this flow in captures cap1'))
        self.assertIn('All traffic from Z4 External to Z1 Cell A: 12 connection(s)', remote.evidence)
        office = flows[('Z5 Office', CONTROL, '')]
        self.assertEqual(office.name, 'Z5 Office -> Z1 Cell A (control) (unidentified)')
        self.assertFalse(office.remote_access)
        self.assertEqual(office.access, [])
        self.assertTrue(office.evidence.startswith('Passively seen: no identified request. All traffic from Z5 Office '
                                                   'to Z1 Cell A: 300 connection(s)'))
        hmi = flows[(SUPERVISORY, CONTROL, 's7comm')]
        self.assertIn('Read Variable x500 [read]', hmi.evidence)
        self.assertEqual(hmi.access, ['read'])
        services = {(sp.ip, sp.protocol, sp.role) for sp in plan.services}
        self.assertEqual(services, {
            ('10.10.10.10', 's7comm', 'server'), ('10.10.10.20', 's7comm', 'client'),
            ('192.168.1.10', 's7comm', 'client'),
        })
        self.assertEqual(plan.asset_levels['10.10.10.20'], '2')

    def test_no_split_by_default(self):
        plan = build_plan(ASSETS, FLOWS, SUMMARY)
        self.assertEqual(set(plan.zones), {'Z1 Cell A', 'Z4 External', 'Z5 Office', 'Outside'})
        self.assertEqual(plan.zones['Z1 Cell A'].purdue_level, '1')
        self.assertEqual(len(plan.flows), 3)

    def test_outside_name_split_all_and_declared_types(self):
        summary = dict(SUMMARY, zones=[{'name': 'Z4 External', 'type': 'external'},
                                       {'name': 'Z1 Cell A', 'type': 'safety'}])
        plan = build_plan(ASSETS, FLOWS, summary, outside_zone='Internet', split_zones=True)
        self.assertIn('Internet', plan.zones)
        self.assertIn(CONTROL, plan.zones)
        self.assertEqual(plan.zones['Internet'].description, 'Addresses not listed in the observations')
        self.assertEqual(plan.zones['Z4 External'].zone_type, 'external')  # level 3, but declared
        self.assertEqual(plan.zones[CONTROL].zone_type, 'safety')  # a split part takes its zone's type

    def test_ports_and_times_come_from_the_input(self):
        assets = [{'ip': '10.0.0.1', 'zone': 'Cell'}, {'ip': '10.0.1.1', 'zone': 'Office'}]
        flows = [
            {'src': '10.0.1.1', 'dst': '10.0.0.1', 'proto': 'modbus', 'port': 1502, 'func': 'Read Coils',
             'first_seen': '2026-10-01T08:00:00Z', 'last_seen': '2026-10-02T08:00:00Z'},
            {'src': '10.0.1.1', 'dst': '10.0.0.1', 'proto': 'modbus', 'port': 502, 'func': 'Write Single Coil',
             'last_seen': '2026-10-05T08:00:00Z'},
            {'src': '10.0.1.1', 'dst': '10.0.0.1', 'proto': 'BACnet', 'port': 47808},
        ]
        summary = {'start': '2026-09-30T00:00:00Z', 'end': '2026-10-06T00:00:00Z'}
        flows_by_protocol = {f.protocol: f for f in build_plan(assets, flows, summary).flows}
        modbus = flows_by_protocol['modbus-tcp']
        self.assertEqual(modbus.port_mappings, ['tcp/1502', 'tcp/502'])
        self.assertEqual(modbus.access, ['read', 'write'])
        self.assertEqual(modbus.first_seen.isoformat(), '2026-09-30T00:00:00+00:00')  # second request: window
        self.assertEqual(modbus.last_seen.isoformat(), '2026-10-05T08:00:00+00:00')
        self.assertEqual(flows_by_protocol['bacnet-ip'].port_mappings, ['udp/47808'])  # BACnet/IP runs over UDP
        server = {(sp.ip, sp.protocol, sp.role): sp for sp in build_plan(assets, flows, summary).services}
        self.assertEqual(server[('10.0.0.1', 'modbus-tcp', 'server')].port_mappings, ['tcp/1502', 'tcp/502'])

    def test_it_protocols_make_flows_but_no_industrial_services(self):
        assets = [{'ip': '10.0.0.1', 'zone': 'Cell'}, {'ip': '10.0.9.9', 'zone': 'MSP', 'remote_access': True}]
        flows = [{'src': '10.0.9.9', 'dst': '10.0.0.1', 'proto': 'RDP', 'port': 3389}]
        plan = build_plan(assets, flows, {})
        self.assertEqual([(f.protocol, f.remote_access, f.port_mappings) for f in plan.flows],
                         [('rdp', True, ['tcp/3389'])])
        self.assertEqual(plan.services, [])

    def test_remote_access_is_explicit_not_guessed_from_role(self):
        assets = [
            {'ip': '10.0.0.1', 'zone': 'Cell', 'role': 'PLC'},
            {'ip': '10.0.1.1', 'zone': 'Office', 'role': 'Core router'},  # a router, but not remote access
            {'ip': '10.0.2.1', 'zone': 'Jump', 'role': 'Jump host', 'remote_access': True},
        ]
        flows = [
            {'src': '10.0.1.1', 'dst': '10.0.0.1', 'proto': 'modbus', 'func': 'Write Single Register'},
            {'src': '10.0.2.1', 'dst': '10.0.0.1', 'proto': 'modbus', 'func': 'Read Holding Registers'},
        ]
        flows_by_pair = {(f.source, f.destination): f for f in build_plan(assets, flows, {}).flows}
        office, jump = flows_by_pair[('Office', 'Cell')], flows_by_pair[('Jump', 'Cell')]
        self.assertFalse(office.remote_access)
        self.assertEqual(office.access, ['write'])
        self.assertTrue(jump.remote_access)  # remote access even though it only reads
        self.assertEqual(jump.access, ['read'])

    def test_modifying_functions_without_write_in_the_name(self):
        assets = [{'ip': '10.0.0.1', 'zone': 'Cell'}, {'ip': '10.0.1.1', 'zone': 'Eng', 'role': 'ES'},
                  {'ip': '10.0.2.1', 'zone': 'Other', 'role': 'Box'}]
        flows = [
            {'src': '10.0.1.1', 'dst': '10.0.0.1', 'proto': 'S7comm', 'func': 'PLC Stop'},
            {'src': '10.0.1.1', 'dst': '10.0.0.1', 'proto': 'S7comm', 'func': 'Request download'},
            {'src': '10.0.2.1', 'dst': '10.0.0.1', 'proto': 'modbus', 'func': 'Force Single Coil'},
        ]
        flows_by_pair = {(f.source, f.destination): f for f in build_plan(assets, flows, {}).flows}
        eng = flows_by_pair[('Eng', 'Cell')]
        self.assertEqual(eng.access, ['control', 'program'])
        self.assertIn('PLC Stop x1 [control]', eng.evidence)
        self.assertIn('Request download x1 [program]', eng.evidence)
        self.assertIn('ES (10.0.1.1)', eng.evidence)
        self.assertEqual(flows_by_pair[('Other', 'Cell')].access, ['write'])

    def test_declared_access_wins_and_unclassified_is_shown(self):
        assets = [{'ip': '10.0.0.1', 'zone': 'Cell'}, {'ip': '10.0.1.1', 'zone': 'Eng', 'role': 'ES'}]
        flows = [
            {'src': '10.0.1.1', 'dst': '10.0.0.1', 'proto': 'S7comm', 'func': 'Vendor thing'},
            {'src': '10.0.1.1', 'dst': '10.0.0.1', 'proto': 'S7comm', 'func': 'Odd one', 'access': 'program'},
            {'src': '10.0.1.1', 'dst': '10.0.0.1', 'proto': 'VendorProto'},
        ]
        flows_by_protocol = {f.protocol: f for f in build_plan(assets, flows, {}).flows}
        s7 = flows_by_protocol['s7comm']
        self.assertIn('Vendor thing x1 [unclassified]', s7.evidence)
        self.assertIn('Odd one x1 [program]', s7.evidence)
        self.assertEqual(s7.access, ['program'])  # unclassified adds no class
        self.assertIn('Protocol not recognised: VendorProto', flows_by_protocol[''].evidence)

    def test_open_port_alone_creates_no_service(self):
        assets = [
            {'ip': '10.0.0.1', 'zone': 'Substation', 'open_ports': [102, 22]},
            {'ip': '10.0.0.2', 'zone': 'Substation', 'open_ports': [102], 'services': [
                {'proto': 'iec-61850-mms', 'port': 102}]},
            {'ip': '10.0.0.3', 'zone': 'Substation', 'open_ports': [102, 502]},
        ]
        flows = [{'src': '10.0.0.2', 'dst': '10.0.0.3', 'proto': 'S7comm', 'func': 'Read Variable'}]
        plan = build_plan(assets, flows, {})
        services = {(sp.ip, sp.protocol, sp.role): sp for sp in plan.services}
        self.assertNotIn('10.0.0.1', {ip for ip, _p, _r in services})  # port 102 open says nothing definite
        mms = services[('10.0.0.2', 'iec-61850-mms', 'server')]
        self.assertEqual(mms.port_mappings, ['tcp/102'])
        self.assertIn('Identified as iec-61850-mms on port 102', mms.evidence[0])
        self.assertIn(('10.0.0.3', 's7comm', 'server'), services)  # it answered S7comm
        unidentified = {(op.ip, op.port): op.candidates for op in plan.unidentified_ports}
        self.assertEqual(unidentified, {
            ('10.0.0.1', 102): ['s7comm', 's7comm-plus', 'iec-61850-mms'],
            ('10.0.0.3', 502): ['modbus-tcp'],  # 102 is explained by the S7comm it answered
        })

    def test_invalid_input(self):
        bad = [
            ([{'ip': '10.0.0.1'}], [], {}, 'zone'),
            ([{'ip': '10.0.0.999', 'zone': 'A'}], [], {}, 'not an IPv4'),
            ([{'ip': '10.0.0.1', 'zone': 'A'}, {'ip': '10.0.0.1', 'zone': 'B'}], [], {}, 'listed twice'),
            ([{'ip': '10.0.0.1', 'zone': 'A', 'remote_access': 'yes'}], [], {}, 'remote_access'),
            ([{'ip': '10.0.0.1', 'zone': 'A', 'services': [{'proto': 'nope'}]}], [], {}, 'known protocol'),
            ([], [{'src': '10.0.0.1', 'dst': '10.0.0.2', 'proto': 'modbus', 'access': 'maybe'}], {}, 'access'),
            ([], [{'src': '10.0.0.1', 'proto': 'modbus'}], {}, 'required'),
            ([], [{'src': '10.0.0.1', 'dst': '10.0.0.2', 'proto': 'modbus', 'port': 70000}], {}, 'port'),
            ([], [{'src': '10.0.0.1', 'dst': '10.0.0.2', 'proto': 'modbus', 'last_seen': 'yesterday'}], {},
             'ISO 8601'),
            ([], [], {'zones': [{'name': 'A', 'type': 'office'}]}, 'type'),
        ]
        for assets, flows, summary, message in bad:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                build_plan(assets, flows, summary)

    def test_only_required_fields(self):
        """assets need ip + zone, flows need src/dst/proto; everything else is optional"""
        assets = [{'ip': '10.0.0.1', 'zone': 'Cell'}, {'ip': '10.0.1.1', 'zone': 'Office'}]
        flows = [{'src': '10.0.1.1', 'dst': '10.0.0.1', 'proto': 'modbus-tcp'}]
        plan = build_plan(assets, flows, {})
        self.assertEqual(set(plan.zones), {'Cell', 'Office'})
        self.assertEqual([(f.source, f.destination) for f in plan.flows], [('Office', 'Cell')])
        self.assertEqual({(s.ip, s.protocol, s.role) for s in plan.services},
                         {('10.0.0.1', 'modbus-tcp', 'server'), ('10.0.1.1', 'modbus-tcp', 'client')})


def make_asset(name, ip, site, vrf=None, vm=False):
    """A device (or VM) at `site` with `ip` as its primary IPv4, optionally in `vrf`."""
    address = IPAddress.objects.create(address=f'{ip}/24', vrf=vrf)
    if vm:
        from virtualization.models import VirtualMachine
        asset = VirtualMachine.objects.create(name=name, site=site)
    else:
        asset = create_test_device(name, site=site)
        iface = Interface.objects.create(device=asset, name='eth0', type='1000base-t')
        address.assigned_object = iface
        address.save()
    asset.primary_ip4 = address
    asset.save()
    return asset


class ImportCommandTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(name='Demo', slug='demo')
        for a in ASSETS:
            make_asset(f"dev-{a['ip']}", a['ip'], cls.site)
        for net in ('10.10.10.0/24', '192.168.1.0/24', '192.168.2.0/24'):
            Prefix.objects.create(prefix=net, scope=cls.site)

    def _run_dir(self, directory, *extra):
        from users.models import User
        if not User.objects.filter(is_superuser=True).exists():
            User.objects.create_superuser('admin')
        out = StringIO()
        call_command('ot_import', directory, '--site', 'demo', *extra, stdout=out)
        return out.getvalue()

    def _run(self, *extra, assets=ASSETS):
        with tempfile.TemporaryDirectory() as tmp:
            for name, data in (('assets', assets), ('flows', FLOWS), ('summary', SUMMARY)):
                Path(tmp, f'{name}.json').write_text(json.dumps(data))
            return self._run_dir(tmp, *extra)

    def test_unknown_import_keeps_what_the_source_knew(self):
        import csv

        from dcim.models import DeviceRole
        DeviceRole.objects.create(name='Engineering station', slug='es')
        assets = ASSETS + [
            {'ip': '10.10.10.30', 'role': 'engineering station', 'purdue_level': 2, 'zone': 'Z1 Cell A'},
            {'ip': '10.10.10.40', 'role': 'PLC (ControlLogix)', 'purdue_level': 1, 'zone': 'Z1 Cell A'},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            self._run('--unknown-import', tmp, assets=assets)
            rows = {r['name']: r for r in csv.DictReader(Path(tmp, '1-devices.csv').open())}
        # A role NetBox has (by name, any case) is filled in; any other stays in the description
        es, plc = rows['unknown-10.10.10.30-demo'], rows['unknown-10.10.10.40-demo']
        self.assertEqual((es['role'], es['cf_ot_purdue_level']), ('Engineering station', '2'))
        self.assertEqual((plc['role'], plc['cf_ot_purdue_level']), ('', '1'))
        self.assertTrue(plc['description'].startswith(
            'Found by passive discovery. Role in the capture: PLC (ControlLogix), In zone Z1 Cell A'))

    def test_dry_run_saves_nothing(self):
        self._run('--dry-run')
        self.assertEqual(Zone.objects.count(), 0)

    def test_traffic_inside_a_zone_and_a_split_that_cannot_happen_are_reported(self):
        out = self._run('--split', 'Z5 Office')
        self.assertIn('--split "Z5 Office": not split, its assets with a Purdue level are all in one band', out)
        self.assertIn('Z1 Cell A: 500 request(s) from 1 host(s)', out)
        self.assertIn('--split "Z1 Cell A" turns this traffic into flows', out)

    def test_levels_from_netbox_count_for_split(self):
        """A level set in NetBox (by hand, or by an earlier import) lets --split work without one in the input."""
        from dcim.models import Device
        for ip, level in (('10.10.10.10', '1'), ('10.10.10.20', '2')):
            device = Device.objects.get(name=f'dev-{ip}')
            device.custom_field_data[PURDUE_CF_NAME] = level
            device.save()
        assets = [{k: v for k, v in a.items() if k != 'purdue_level'} for a in ASSETS]
        out = self._run('--split', 'Z1 Cell A', assets=assets)
        self.assertIn('Purdue levels from NetBox for 2 asset(s)', out)
        self.assertTrue(Flow.objects.filter(source_zone__name=SUPERVISORY, destination_zone__name=CONTROL).exists())

    def test_import_and_rerun(self):
        prefixes_before = Prefix.objects.count()
        out = self._run('--split', 'Z1 Cell A')
        self.assertEqual(Zone.objects.filter(site=self.site).count(), 5)
        self.assertEqual(Flow.objects.count(), 4)
        self.assertEqual(Zone.objects.get(name='Outside').zone_type, 'external')
        control = Zone.objects.get(name=CONTROL)
        self.assertEqual(list(control.devices.values_list('name', flat=True)), ['dev-10.10.10.10'])
        # The /24 holds both halves of the split zone, so it is linked to neither
        self.assertFalse(control.prefixes.exists())
        self.assertIn('prefix 10.10.10.0/24 holds assets of zones', out)
        self.assertEqual(list(Zone.objects.get(name='Z5 Office').prefixes.values_list('prefix', flat=True)),
                         [Prefix.objects.get(prefix='192.168.2.0/24').prefix])
        self.assertEqual(Prefix.objects.count(), prefixes_before)  # never creates prefixes
        hmi = Zone.objects.get(name=SUPERVISORY).devices.get(name='dev-10.10.10.20')
        self.assertEqual(hmi.custom_field_data[PURDUE_CF_NAME], '2')
        plc_s7 = IndustrialService.objects.get(device__name='dev-10.10.10.10', protocol='s7comm')
        self.assertEqual(plc_s7.role, 'server')
        self.assertIsNone(plc_s7.service)  # no port in the input: no application service
        self.assertEqual(IndustrialService.objects.count(), 3)
        self.assertIn('10.10.10.10 port 502: modbus-tcp?', out)  # open, not identified, no service

        # A human decision survives a re-import
        flow = Flow.objects.get(source_zone__name='Z4 External')
        self.assertTrue(flow.remote_access)
        self.assertEqual(flow.access, ['read', 'write'])
        flow.allowed = 'no'
        flow.save()
        out = self._run('--split', 'Z1 Cell A')
        self.assertIn('flows unchanged: 4', out)
        self.assertIn('services unchanged: 3', out)
        flow.refresh_from_db()
        self.assertEqual(flow.allowed, 'no')
        self.assertEqual(Zone.objects.count(), 5)

    def test_flows_join_the_only_conduit_and_servers_get_ports(self):
        cell = Zone.objects.create(name='Z1 Cell A', slug='z1-cell-a', site=self.site, purdue_level='1')
        external = Zone.objects.create(name='Z4 External', slug='z4-external', site=self.site, zone_type='external')
        conduit = Conduit.objects.create(name='Supplier access', site=self.site)
        conduit.zones.set([cell, external])
        flows = [dict(f, port=102) for f in FLOWS]
        with tempfile.TemporaryDirectory() as tmp:
            for name, data in (('assets', ASSETS), ('flows', flows), ('summary', SUMMARY)):
                Path(tmp, f'{name}.json').write_text(json.dumps(data))
            self._run_dir(tmp)
        flow = Flow.objects.get(source_zone=external, destination_zone=cell)
        self.assertEqual(flow.conduit, conduit)
        self.assertEqual(flow.port_mappings, ['tcp/102'])
        self.assertIsNone(Flow.objects.get(source_zone__name='Z5 Office', destination_zone=cell).conduit)
        plc_s7 = IndustrialService.objects.get(device__name='dev-10.10.10.10', protocol='s7comm')
        self.assertEqual(plc_s7.service.port_mappings, ['tcp/102'])
        self.assertEqual([str(ip) for ip in plc_s7.service.ipaddresses.all()], ['10.10.10.10/24'])
        self.assertEqual(Service.objects.count(), 1)
        self.assertEqual(Zone.objects.get(pk=external.pk).zone_type, 'external')  # existing zones keep their type

    def test_unsplit_zone_gets_its_prefix(self):
        self._run()
        self.assertEqual([str(p.prefix) for p in Zone.objects.get(name='Z1 Cell A').prefixes.all()],
                         ['10.10.10.0/24'])

    def test_rename_option_removed(self):
        with self.assertRaises(CommandError):
            self._run('--rename', 'Z5 Office=Office')

    def test_invalid_input_is_a_command_error(self):
        with self.assertRaisesRegex(CommandError, 'Invalid input'):
            self._run(assets=[{'ip': 'nope', 'zone': 'A'}])

    def test_unknown_vrf(self):
        with self.assertRaisesRegex(CommandError, 'not found'):
            self._run('--vrf', 'nope')


class SiteAndVRFScopeTest(TestCase):
    """The same machine network exists at every site and behind every OEM machine; matching must not cross."""

    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name='Region', slug='region')
        cls.site_a = Site.objects.create(name='Plant A', slug='plant-a', region=region)
        cls.site_b = Site.objects.create(name='Plant B', slug='plant-b', region=region)
        cls.vrf = VRF.objects.create(name='Machine 7')
        cls.plc_a = make_asset('plc-a', '192.168.0.10', cls.site_a)
        cls.plc_b = make_asset('plc-b', '192.168.0.10', cls.site_b)
        cls.plc_vrf = make_asset('plc-a-m7', '192.168.0.10', cls.site_a, vrf=cls.vrf)
        cls.hmi_a = make_asset('hmi-a', '192.168.0.20', cls.site_a, vm=True)
        cls.hmi_b = make_asset('hmi-b', '192.168.0.20', cls.site_b, vm=True)
        cls.net_a = Prefix.objects.create(prefix='192.168.0.0/24', scope=cls.site_a)
        cls.net_b = Prefix.objects.create(prefix='192.168.0.0/24', scope=cls.site_b)
        cls.net_vrf = Prefix.objects.create(prefix='192.168.0.0/24', vrf=cls.vrf, scope=cls.site_a)
        Prefix.objects.create(prefix='192.168.0.0/16', status='container')
        Prefix.objects.create(prefix='192.168.0.0/20', scope=region)  # broader, loses to the /24

    def _apply(self, site, vrf=None, assets=None):
        assets = assets or [{'ip': '192.168.0.10', 'zone': 'Cell', 'purdue_level': 1},
                            {'ip': '192.168.0.20', 'zone': 'Cell', 'purdue_level': 2}]
        flows = [{'src': '192.168.0.20', 'dst': '192.168.0.10', 'proto': 'modbus', 'func': 'Read Coils'}]
        lines = []
        stats = apply_plan(build_plan(assets, flows, {}), site, vrf=vrf, log=lines.append)
        return Zone.objects.get(site=site, name='Cell'), stats, lines

    def test_global_table_of_one_site(self):
        zone, stats, _lines = self._apply(self.site_a)
        self.assertEqual(list(zone.devices.all()), [self.plc_a])
        self.assertEqual(list(zone.virtual_machines.all()), [self.hmi_a])
        self.assertEqual(list(zone.prefixes.all()), [self.net_a])
        self.assertEqual(set(IndustrialService.objects.values_list('device__name', 'virtual_machine__name')),
                         {('plc-a', None), (None, 'hmi-a')})
        self.assertNotIn('assets not found in NetBox', stats)

    def test_other_site(self):
        zone, _stats, _lines = self._apply(self.site_b)
        self.assertEqual(list(zone.devices.all()), [self.plc_b])
        self.assertEqual(list(zone.prefixes.all()), [self.net_b])

    def test_vrf(self):
        zone, stats, lines = self._apply(self.site_a, vrf=self.vrf)
        self.assertEqual(list(zone.devices.all()), [self.plc_vrf])
        self.assertEqual(list(zone.prefixes.all()), [self.net_vrf])
        self.assertFalse(zone.virtual_machines.exists())  # the HMI VM is in the global table
        self.assertEqual(stats['assets not found in NetBox'], 1)
        self.assertIn('192.168.0.20: no device or VM with this primary IPv4 (site Plant A, VRF Machine 7)', lines)

    def test_duplicates_in_one_site_and_vrf_are_skipped(self):
        make_asset('plc-a-twin', '192.168.0.10', self.site_a)
        zone, stats, lines = self._apply(self.site_a)
        self.assertFalse(zone.devices.exists())
        self.assertEqual(stats['assets matched more than once (skipped)'], 1)
        self.assertTrue(any('several devices/VMs' in line for line in lines))

    def test_no_prefix_is_created_or_guessed(self):
        count = Prefix.objects.count()
        zone, stats, lines = self._apply(self.site_a, assets=[{'ip': '192.168.200.1', 'zone': 'Cell'}])
        self.assertEqual(Prefix.objects.count(), count)
        self.assertFalse(zone.prefixes.exists())  # the /16 container does not count
        self.assertEqual(stats['addresses without a prefix in NetBox'], 1)

    def test_region_prefix_when_the_site_has_none(self):
        zone, _stats, _lines = self._apply(self.site_b, assets=[{'ip': '192.168.5.1', 'zone': 'Cell'}])
        self.assertEqual([str(p.prefix) for p in zone.prefixes.all()], ['192.168.0.0/20'])
