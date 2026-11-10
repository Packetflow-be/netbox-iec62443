import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from dcim.models import Interface, Region, Site
from ipam.models import VRF, IPAddress, Prefix
from utilities.testing import create_test_device

from netbox_iec62443.customfields import PURDUE_CF_NAME
from netbox_iec62443.importers import functions
from netbox_iec62443.importers.observations import apply_plan, build_plan
from netbox_iec62443.models import Conduit, IndustrialService, Zone

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

    def test_plan_splits_mixed_zone(self):
        plan = build_plan(ASSETS, FLOWS, SUMMARY, split_zones=['Z1 Cell A'])
        self.assertEqual(set(plan.zones), {CONTROL, SUPERVISORY, 'Z4 External', 'Z5 Office', 'Outside'})
        self.assertEqual(plan.zones[CONTROL].member_ips, ['10.10.10.10'])
        self.assertEqual(plan.zones[CONTROL].purdue_level, '1')
        self.assertEqual(plan.zones[SUPERVISORY].purdue_level, '2')
        self.assertEqual(plan.zones['Outside'].purdue_level, '')
        pairs = {(c.source, c.destination): c for c in plan.conduits}
        self.assertEqual(set(pairs), {
            ('Z4 External', CONTROL),  # pinned to the PLC by its OT requests
            ('Z5 Office', CONTROL),  # no OT requests: the most critical part
            ('Z5 Office', 'Outside'),
            (SUPERVISORY, CONTROL),  # inside the old zone, now a conduit
        })
        remote = pairs[('Z4 External', CONTROL)]
        self.assertTrue(remote.remote_access)
        self.assertIn('192.168.1.10', remote.via)
        self.assertIn('S7comm', remote.protocols)
        self.assertIn('Write Variable x12 [write]', remote.evidence)
        self.assertIn('12 connection(s) from Z4 External to Z1 Cell A', remote.evidence)
        office = pairs[('Z5 Office', CONTROL)]
        self.assertFalse(office.remote_access)
        self.assertEqual(office.via, '')
        hmi = pairs[(SUPERVISORY, CONTROL)]
        self.assertIn('Read Variable x500 [read]', hmi.evidence)
        self.assertEqual(hmi.via, '')  # reads only
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
        self.assertEqual(len(plan.conduits), 3)

    def test_outside_name_and_split_all(self):
        plan = build_plan(ASSETS, FLOWS, SUMMARY, outside_zone='Internet', split_zones=True)
        self.assertIn('Internet', plan.zones)
        self.assertIn(CONTROL, plan.zones)
        self.assertEqual(plan.zones['Internet'].description, 'Addresses not listed in the observations')

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
        pairs = {(c.source, c.destination): c for c in build_plan(assets, flows, {}).conduits}
        office, jump = pairs[('Office', 'Cell')], pairs[('Jump', 'Cell')]
        self.assertFalse(office.remote_access)
        self.assertEqual(office.via, 'Core router (10.0.1.1)')  # it writes
        self.assertTrue(jump.remote_access)  # remote access even though it only reads
        self.assertEqual(jump.via, 'Jump host (10.0.2.1)')

    def test_modifying_functions_without_write_in_the_name(self):
        assets = [{'ip': '10.0.0.1', 'zone': 'Cell'}, {'ip': '10.0.1.1', 'zone': 'Eng', 'role': 'ES'},
                  {'ip': '10.0.2.1', 'zone': 'Other', 'role': 'Box'}]
        flows = [
            {'src': '10.0.1.1', 'dst': '10.0.0.1', 'proto': 'S7comm', 'func': 'PLC Stop'},
            {'src': '10.0.1.1', 'dst': '10.0.0.1', 'proto': 'S7comm', 'func': 'Request download'},
            {'src': '10.0.2.1', 'dst': '10.0.0.1', 'proto': 'modbus', 'func': 'Force Single Coil'},
        ]
        pairs = {(c.source, c.destination): c for c in build_plan(assets, flows, {}).conduits}
        self.assertEqual(pairs[('Eng', 'Cell')].via, 'ES (10.0.1.1)')
        self.assertIn('PLC Stop x1 [control]', pairs[('Eng', 'Cell')].evidence)
        self.assertIn('Request download x1 [program]', pairs[('Eng', 'Cell')].evidence)
        self.assertEqual(pairs[('Other', 'Cell')].via, 'Box (10.0.2.1)')

    def test_declared_access_wins_and_unclassified_is_shown(self):
        assets = [{'ip': '10.0.0.1', 'zone': 'Cell'}, {'ip': '10.0.1.1', 'zone': 'Eng', 'role': 'ES'}]
        flows = [
            {'src': '10.0.1.1', 'dst': '10.0.0.1', 'proto': 'S7comm', 'func': 'Vendor thing'},
            {'src': '10.0.1.1', 'dst': '10.0.0.1', 'proto': 'S7comm', 'func': 'Odd one', 'access': 'program'},
        ]
        conduit = build_plan(assets, flows, {}).conduits[0]
        self.assertIn('Vendor thing x1 [unclassified]', conduit.evidence)
        self.assertIn('Odd one x1 [program]', conduit.evidence)
        self.assertEqual(conduit.via, 'ES (10.0.1.1)')

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
        self.assertEqual(mms.ports, [102])
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
        self.assertEqual([(c.source, c.destination) for c in plan.conduits], [('Office', 'Cell')])
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

    def _run(self, *extra, assets=ASSETS):
        from users.models import User
        if not User.objects.filter(is_superuser=True).exists():
            User.objects.create_superuser('admin')
        with tempfile.TemporaryDirectory() as tmp:
            for name, data in (('assets', assets), ('flows', FLOWS), ('summary', SUMMARY)):
                Path(tmp, f'{name}.json').write_text(json.dumps(data))
            out = StringIO()
            call_command('iec62443_import', tmp, '--site', 'demo', *extra, stdout=out)
            return out.getvalue()

    def test_dry_run_saves_nothing(self):
        self._run('--dry-run')
        self.assertEqual(Zone.objects.count(), 0)

    def test_import_and_rerun(self):
        prefixes_before = Prefix.objects.count()
        out = self._run('--split', 'Z1 Cell A')
        self.assertEqual(Zone.objects.filter(site=self.site).count(), 5)
        self.assertEqual(Conduit.objects.count(), 4)
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
        self.assertEqual((plc_s7.role, plc_s7.ports, plc_s7.interface.name), ('server', [102], 'eth0'))
        self.assertEqual(IndustrialService.objects.count(), 3)
        self.assertIn('10.10.10.10 port 502: modbus-tcp?', out)  # open, not identified, no service

        # A human decision survives a re-import
        conduit = Conduit.objects.get(source_zone__name='Z4 External')
        self.assertTrue(conduit.remote_access)
        conduit.allowed = 'no'
        conduit.save()
        out = self._run('--split', 'Z1 Cell A')
        self.assertIn('conduits unchanged: 4', out)
        self.assertIn('services unchanged: 3', out)
        conduit.refresh_from_db()
        self.assertEqual(conduit.allowed, 'no')
        self.assertEqual(Zone.objects.count(), 5)

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
