from io import StringIO
import json
import tempfile
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
    {'ip': '10.10.10.10', 'role': 'PLC', 'purdue_level': 1, 'zone': 'Z1 Cel A'},
    {'ip': '10.10.10.20', 'role': 'HMI', 'purdue_level': 2, 'zone': 'Z1 Cel A'},
    {'ip': '192.168.1.10', 'role': 'Router van buitenaf (schrijft naar PLC)', 'purdue_level': 3,
     'zone': 'Z4 Van buitenaf'},
    {'ip': '192.168.2.42', 'role': 'Laptop', 'purdue_level': 4, 'zone': 'Z5 Kantoor'},
]
FLOWS = [
    {'src': '10.10.10.20', 'dst': '10.10.10.10', 'proto': 'S7comm', 'func': 'Read Variable', 'count': 500},
    {'src': '192.168.1.10', 'dst': '10.10.10.10', 'proto': 'S7comm', 'func': 'Write Variable', 'count': 12},
    {'src': '192.168.1.10', 'dst': '10.10.10.10', 'proto': 'S7comm', 'func': 'Read Variable', 'count': 12},
]
SUMMARY = {
    'captures': ['cap1'], 'hours': 2.0,
    'zone_pairs': [
        {'from': 'Z4 Van buitenaf', 'to': 'Z1 Cel A', 'count': 12},
        {'from': 'Z5 Kantoor', 'to': 'Z1 Cel A', 'count': 300},
        {'from': 'Z5 Kantoor', 'to': 'Onbekend', 'count': 40},
    ],
}


class BuildPlanTest(TestCase):

    def test_plan(self):
        plan = build_plan(ASSETS, FLOWS, SUMMARY)
        self.assertEqual(set(plan.zones), {'Z1 Cel A', 'Z4 Van buitenaf', 'Z5 Kantoor', 'Onbekend'})
        cell = plan.zones['Z1 Cel A']
        self.assertEqual(cell.purdue_level, '1')  # lowest level of its members
        self.assertEqual(cell.prefixes, ['10.10.10.0/24'])
        self.assertEqual(plan.zones['Onbekend'].purdue_level, '')
        remote = next(c for c in plan.conduits if c.source == 'Z4 Van buitenaf')
        self.assertTrue(remote.remote_access)
        self.assertIn('192.168.1.10', remote.via)
        self.assertIn('S7comm', remote.protocols)
        self.assertIn('Write Variable x12', remote.evidence)
        office = next(c for c in plan.conduits if c.source == 'Z5 Kantoor' and c.destination == 'Z1 Cel A')
        self.assertFalse(office.remote_access)
        self.assertEqual(office.via, '')
        self.assertEqual(plan.asset_levels['10.10.10.20'], '2')


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
        self._run()
        self.assertEqual(Zone.objects.filter(site=self.site).count(), 4)
        self.assertEqual(Conduit.objects.count(), 3)
        cell = Zone.objects.get(name='Z1 Cel A')
        self.assertEqual(cell.devices.count(), 2)
        self.assertTrue(cell.prefixes.filter(prefix='10.10.10.0/24').exists())
        hmi = cell.devices.get(name='dev-10.10.10.20')
        self.assertEqual(hmi.custom_field_data[PURDUE_CF_NAME], '2')

        # A human decision survives a re-import
        conduit = Conduit.objects.get(source_zone__name='Z4 Van buitenaf')
        conduit.allowed = 'no'
        conduit.save()
        out = self._run()
        self.assertIn('conduits unchanged: 3', out)
        conduit.refresh_from_db()
        self.assertEqual(conduit.allowed, 'no')
        self.assertEqual(Zone.objects.count(), 4)
        self.assertEqual(Prefix.objects.filter(prefix='10.10.10.0/24').count(), 1)
