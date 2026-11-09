import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from dcim.models import Interface, Site
from ipam.models import IPAddress, Prefix
from utilities.testing import create_test_device

from netbox_iec62443.customfields import PURDUE_CF_NAME
from netbox_iec62443.importers.vloerscan import build_plan
from netbox_iec62443.models import Conduit, Zone

# A small excerpt in the shape of the Vloerscan prototype's output (documentation addresses, no real site)
ASSETS = [
    {'ip': '10.10.10.10', 'role': 'PLC', 'purdue_level': 1, 'zone': 'Z1 Cell A'},
    {'ip': '10.10.10.20', 'role': 'HMI', 'purdue_level': 2, 'zone': 'Z1 Cell A'},
    {'ip': '192.168.1.10', 'role': 'Router from outside (writes to PLC)', 'purdue_level': 3,
     'zone': 'Z4 External'},
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


class BuildPlanTest(TestCase):

    def test_plan_splits_mixed_zone(self):
        plan = build_plan(ASSETS, FLOWS, SUMMARY, split_zones=['Z1 Cell A'])
        self.assertEqual(set(plan.zones), {CONTROL, SUPERVISORY, 'Z4 External', 'Z5 Office', 'Outside'})
        self.assertEqual(plan.zones[CONTROL].member_ips, ['10.10.10.10'])
        self.assertEqual(plan.zones[CONTROL].purdue_level, '1')
        self.assertEqual(plan.zones[SUPERVISORY].purdue_level, '2')
        self.assertEqual(plan.zones[CONTROL].prefixes, ['10.10.10.0/24'])
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
        self.assertIn('Write Variable x12', remote.evidence)
        self.assertIn('12 connection(s) from Z4 External to Z1 Cell A', remote.evidence)
        office = pairs[('Z5 Office', CONTROL)]
        self.assertFalse(office.remote_access)
        self.assertEqual(office.via, '')
        hmi = pairs[(SUPERVISORY, CONTROL)]
        self.assertIn('Read Variable x500', hmi.evidence)
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

    def test_rename_and_outside_name(self):
        plan = build_plan(ASSETS, FLOWS, SUMMARY, renames={'Z4 External': 'Z4 Remote'}, outside_zone='Internet',
                          split_zones=True)
        self.assertIn('Z4 Remote', plan.zones)
        self.assertNotIn('Z4 External', plan.zones)
        self.assertIn('Internet', plan.zones)
        self.assertTrue(any(c.source == 'Z4 Remote' and c.remote_access for c in plan.conduits))


class ImportCommandTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(name='Demo', slug='demo')
        for a in ASSETS:
            device = create_test_device(f"dev-{a['ip']}", site=cls.site)
            iface = Interface.objects.create(device=device, name='eth0', type='1000base-t')
            ip = IPAddress.objects.create(address=f"{a['ip']}/24", assigned_object=iface)
            device.primary_ip4 = ip
            device.save()

    def _run(self, *extra):
        with tempfile.TemporaryDirectory() as tmp:
            for name, data in (('assets', ASSETS), ('flows', FLOWS), ('summary', SUMMARY)):
                Path(tmp, f'{name}.json').write_text(json.dumps(data))
            out = StringIO()
            call_command('iec62443_import_vloerscan', tmp, '--site', 'demo', *extra, stdout=out)
            return out.getvalue()

    def test_dry_run_saves_nothing(self):
        from users.models import User
        User.objects.create_superuser('admin')
        self._run('--dry-run')
        self.assertEqual(Zone.objects.count(), 0)

    def test_import_and_rerun(self):
        from users.models import User
        User.objects.create_superuser('admin')
        self._run('--split', 'Z1 Cell A')
        self.assertEqual(Zone.objects.filter(site=self.site).count(), 5)
        self.assertEqual(Conduit.objects.count(), 4)
        control = Zone.objects.get(name=CONTROL)
        self.assertEqual(list(control.devices.values_list('name', flat=True)), ['dev-10.10.10.10'])
        self.assertTrue(control.prefixes.filter(prefix='10.10.10.0/24').exists())
        hmi = Zone.objects.get(name=SUPERVISORY).devices.get(name='dev-10.10.10.20')
        self.assertEqual(hmi.custom_field_data[PURDUE_CF_NAME], '2')
        from netbox_iec62443.models import IndustrialService
        plc_s7 = IndustrialService.objects.get(device__name='dev-10.10.10.10', protocol='s7comm')
        self.assertEqual((plc_s7.role, plc_s7.ports, plc_s7.interface.name), ('server', [102], 'eth0'))
        self.assertEqual(IndustrialService.objects.count(), 3)

        # A human decision survives a re-import
        conduit = Conduit.objects.get(source_zone__name='Z4 External')
        conduit.allowed = 'no'
        conduit.save()
        out = self._run('--split', 'Z1 Cell A')
        self.assertIn('conduits unchanged: 4', out)
        self.assertIn('services unchanged: 3', out)
        conduit.refresh_from_db()
        self.assertEqual(conduit.allowed, 'no')
        self.assertEqual(Zone.objects.count(), 5)
        self.assertEqual(Prefix.objects.filter(prefix='10.10.10.0/24').count(), 1)

    def test_rename_option(self):
        from users.models import User
        User.objects.create_superuser('admin')
        self._run('--rename', 'Z5 Office=Office')
        self.assertTrue(Zone.objects.filter(name='Office').exists())
        self.assertTrue(Zone.objects.filter(name='Z1 Cell A').exists())

    def test_split_by_input_name_after_rename(self):
        plan = build_plan(ASSETS, FLOWS, SUMMARY, renames={'Z1 Cell A': 'Cell'}, split_zones=['Z1 Cell A'])
        self.assertIn('Cell (control)', plan.zones)
