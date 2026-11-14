import csv
import gzip
import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from dcim.models import Interface, Site
from ipam.models import IPAddress, Prefix
from utilities.testing import create_test_device

from netbox_ot.importers import zeek
from netbox_ot.importers.netbox_zones import zone_map_from_netbox
from netbox_ot.importers.observations import build_plan
from netbox_ot.models import Flow, IndustrialService, Zone

T0 = 1793520000  # 2026-11-01T08:00:00Z

CONN_FIELDS = ('ts', 'uid', 'id.orig_h', 'id.orig_p', 'id.resp_h', 'id.resp_p', 'proto', 'service', 'duration',
               'orig_bytes', 'resp_bytes', 'conn_state', 'local_orig', 'local_resp', 'missed_bytes', 'history',
               'orig_pkts', 'orig_ip_bytes', 'resp_pkts', 'resp_ip_bytes', 'tunnel_parents')
CONN = [
    # uid, orig, resp, port, proto, service, state
    ('C1', '10.10.20.5', '10.10.10.10', 502, 'tcp', 'modbus', 'SF'),
    ('C2', '10.10.20.5', '10.10.10.10', 102, 'tcp', 'cotp,s7comm', 'SF'),
    ('C3', '192.168.50.7', '10.10.20.5', 3389, 'tcp', 'rdp', 'SF'),  # MSP into the HMI zone
    ('C4', '10.10.20.5', '10.10.10.11', 102, 'tcp', '-', 'S0'),  # never answered: skipped
    ('C5', '10.10.10.10', '10.10.30.2', 514, 'udp', 'syslog', 'S0'),  # one-way UDP: counts
    ('C6', '10.10.20.5', '10.10.10.99', 445, 'tcp', '-', 'SF'),  # unknown host, unidentified port
    ('C7', '10.10.20.5', '10.10.10.255', 47808, 'udp', 'bacnet', 'S0'),  # broadcast: skipped
    ('C8', '10.10.20.5', '224.0.0.251', 5353, 'udp', 'dns', 'S0'),  # multicast: skipped
    ('C9', 'fe80::1', 'fe80::2', 22, 'tcp', 'ssh', 'SF'),  # IPv6: skipped
    ('C10', '10.10.20.5', '10.10.10.99', 3, 'icmp', '-', 'OTH'),  # ICMP: type/code in the port fields
]
MODBUS = [  # Zeek's own modbus.log: every record is a request
    ('C1', 'READ_HOLDING_REGISTERS'), ('C1', 'READ_HOLDING_REGISTERS'), ('C1', 'WRITE_SINGLE_REGISTER'),
]
S7COMM = [  # ICSNPP s7comm.log as JSON: only is_orig records are requests
    {'uid': 'C2', 'is_orig': True, 'rosctr_name': 'Job', 'function_name': 'Read Variable'},
    {'uid': 'C2', 'is_orig': False, 'rosctr_name': 'Ack_Data', 'function_name': 'Read Variable'},
    {'uid': 'C2', 'is_orig': True, 'rosctr_name': 'Job', 'function_name': 'PLC Stop'},
]


def tsv(path, stream, fields, rows):
    lines = ['#separator \\x09', '#set_separator\t,', '#empty_field\t(empty)', '#unset_field\t-', f'#path\t{stream}',
             '#fields\t' + '\t'.join(fields), '#types\t' + '\t'.join('string' for _ in fields)]
    lines += ['\t'.join(str(v) for v in row) for row in rows]
    Path(path).write_text('\n'.join(lines) + '\n#close\t2026-11-01-09-00-00\n')


def write_logs(directory):
    conn_rows = []
    for i, (uid, orig, resp, port, proto, service, state) in enumerate(CONN):
        conn_rows.append((T0 + i, uid, orig, 50000 + i, resp, port, proto, service, '1.0', 10, 10, state, '-', '-', 0,
                          'ShADadFf', 1, 1, 1, 1, '-'))
    tsv(Path(directory, 'conn.log'), 'conn', CONN_FIELDS, conn_rows)
    tsv(Path(directory, 'modbus.log'), 'modbus',
        ('ts', 'uid', 'id.orig_h', 'id.orig_p', 'id.resp_h', 'id.resp_p', 'func', 'exception'),
        [(T0 + 10 + i, uid, '10.10.20.5', 50000, '10.10.10.10', 502, func, '-')
         for i, (uid, func) in enumerate(MODBUS)])
    with gzip.open(Path(directory, 's7comm.00:00:00-01:00:00.log.gz'), 'wt') as f:
        for i, record in enumerate(S7COMM):
            f.write(json.dumps({'ts': T0 + 20 + i, 'id': {'orig_h': '10.10.20.5', 'orig_p': 50001,
                                                          'resp_h': '10.10.10.10', 'resp_p': 102}, **record}) + '\n')


ZONES = zeek.ZoneMap(networks={'10.10.10.0/24': 'Cell', '10.10.20.0/24': 'Control room',
                               '10.10.30.0/24': 'Servers'},
                     addresses={'10.10.10.10': 'Cell PLCs'})


class ReadLogsTest(SimpleTestCase):

    def test_tsv_json_and_gzip(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_logs(tmp)
            logs = zeek.read_logs(tmp)
            self.assertTrue(zeek.is_zeek_directory(tmp))
        self.assertEqual(set(logs), {'conn', 'modbus', 's7comm'})
        self.assertEqual(len(logs['conn']), len(CONN))
        self.assertEqual(logs['conn'][3]['service'], None)  # "-" is unset
        self.assertEqual(logs['s7comm'][0]['id.orig_h'], '10.10.20.5')  # nested JSON flattened

    def test_zone_map(self):
        self.assertEqual(ZONES.zone_of('10.10.10.10'), 'Cell PLCs')  # an exact address wins
        self.assertEqual(ZONES.zone_of('10.10.10.11'), 'Cell')
        self.assertIsNone(ZONES.zone_of('8.8.8.8'))
        self.assertTrue(ZONES.is_broadcast('10.10.10.255'))
        with tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False) as f:
            f.write('network,zone,purdue_level,type\n192.168.50.0/24,MSP,,external\n10.10.30.2,Historian,3\n')
        zones = zeek.ZoneMap.from_csv(f.name, base=ZONES)
        self.assertEqual(zones.zone_of('192.168.50.7'), 'MSP')
        self.assertEqual(zones.zone_of('10.10.30.2'), 'Historian')
        self.assertEqual((zones.levels, zones.types), ({'Historian': '3'}, {'MSP': 'external'}))
        Path(f.name).write_text('not-a-network,X\n')
        with self.assertRaisesRegex(ValueError, 'not an address or network'):
            zeek.ZoneMap.from_csv(f.name)


class ToObservationsTest(SimpleTestCase):

    def setUp(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_logs(tmp)
            self.assets, self.flows, self.summary = zeek.to_observations(zeek.read_logs(tmp), ZONES, ['site-a'])

    def _flows(self):
        return {(f['src'], f['dst'], f['proto'], f.get('func', '')): f for f in self.flows}

    def test_requests_from_protocol_logs(self):
        flows = self._flows()
        self.assertEqual(flows[('10.10.20.5', '10.10.10.10', 'modbus', 'READ_HOLDING_REGISTERS')]['count'], 2)
        self.assertIn(('10.10.20.5', '10.10.10.10', 'modbus', 'WRITE_SINGLE_REGISTER'), flows)
        s7 = flows[('10.10.20.5', '10.10.10.10', 's7comm', 'Read Variable')]
        self.assertEqual((s7['count'], s7['port']), (1, 102))  # the response is not a request
        self.assertIn(('10.10.20.5', '10.10.10.10', 's7comm', 'PLC Stop'), flows)

    def test_connections_without_protocol_log(self):
        flows = self._flows()
        self.assertIn(('192.168.50.7', '10.10.20.5', 'rdp', ''), flows)  # from Zeek's payload detection
        self.assertIn(('10.10.10.10', '10.10.30.2', 'syslog', ''), flows)  # one-way UDP counts
        self.assertIn(('10.10.20.5', '10.10.10.99', 'tcp/445', ''), flows)  # no protocol guessed from the port
        icmp = flows[('10.10.20.5', '10.10.10.99', 'icmp', '')]  # ICMP type/code are not ports
        self.assertNotIn('port', icmp)
        self.assertNotIn('transport', icmp)
        # connections covered by a protocol log are not counted twice; unanswered, broadcast, multicast and IPv6 skip
        self.assertNotIn(('10.10.20.5', '10.10.10.10', 'modbus', ''), flows)
        self.assertFalse({'10.10.10.11', '10.10.10.255', '224.0.0.251', 'fe80::2'} & {f['dst'] for f in self.flows})

    def test_assets_and_summary(self):
        assets = {a['ip']: a for a in self.assets}
        self.assertEqual(set(assets), {'10.10.10.10', '10.10.10.99', '10.10.20.5', '10.10.30.2'})  # MSP: outside
        self.assertEqual(assets['10.10.10.10']['zone'], 'Cell PLCs')
        self.assertEqual(assets['10.10.10.10']['open_ports'], [102, 502])
        self.assertEqual(self.summary['start'], '2026-11-01T08:00:00+00:00')
        self.assertEqual(self.summary['captures'], ['site-a'])

    def test_the_plan_classifies_and_flags_remote_access(self):
        plan = build_plan(self.assets, self.flows, self.summary)
        flows = {(f.source, f.destination, f.protocol): f for f in plan.flows}
        s7 = flows[('Control room', 'Cell PLCs', 's7comm')]
        self.assertEqual(s7.access, ['read', 'control'])
        self.assertEqual(s7.port_mappings, ['tcp/102'])
        self.assertEqual(flows[('Control room', 'Cell PLCs', 'modbus-tcp')].access, ['read', 'write'])
        self.assertIn(('Outside', 'Control room', 'rdp'), flows)
        self.assertEqual(flows[('Control room', 'Cell', '')].port_mappings, ['tcp/445'])
        self.assertEqual(plan.hosts['10.10.10.99'].zone, 'Cell')


def asset(name, ip, site):
    device = create_test_device(name, site=site)
    iface = Interface.objects.create(device=device, name='eth0', type='1000base-t')
    device.primary_ip4 = IPAddress.objects.create(address=f'{ip}/24', assigned_object=iface)
    device.save()
    return device


class ZeekImportCommandTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        from users.models import User
        User.objects.create_superuser('admin')
        cls.site = Site.objects.create(name='Plant', slug='plant')
        cls.plc = asset('plc-1', '10.10.10.10', cls.site)
        cls.hmi = asset('hmi-1', '10.10.20.5', cls.site)
        cell = Zone.objects.create(name='Cell', slug='cell', site=cls.site, purdue_level='1')
        cell.prefixes.add(Prefix.objects.create(prefix='10.10.10.0/24', scope=cls.site))
        cell.devices.add(cls.plc)
        control = Zone.objects.create(name='Control room', slug='control-room', site=cls.site, purdue_level='2')
        control.devices.add(cls.hmi)

    def test_zone_map_from_netbox(self):
        zones = zone_map_from_netbox(self.site)
        self.assertEqual(zones.zone_of('10.10.10.10'), 'Cell')
        self.assertEqual(zones.zone_of('10.10.10.99'), 'Cell')  # prefix
        self.assertEqual(zones.zone_of('10.10.20.5'), 'Control room')  # member address
        self.assertIsNone(zones.zone_of('10.10.20.6'))  # no prefix for the control room

    def test_import_with_zone_map_and_unknown_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_logs(tmp)
            Path(tmp, 'zones.csv').write_text('192.168.50.0/24,MSP,,external\n10.10.30.0/24,Servers,3\n')
            report = Path(tmp, 'unknown.csv')
            out = StringIO()
            call_command('ot_import', tmp, '--site', 'plant', '--zone-map', str(Path(tmp, 'zones.csv')),
                         '--unknown-report', str(report), stdout=out)
            rows = list(csv.DictReader(report.open()))
        output = out.getvalue()
        self.assertIn('Zeek logs: conn (9), modbus (3), s7comm (3)', output)
        self.assertEqual(Zone.objects.get(name='MSP').zone_type, 'external')
        msp = Flow.objects.get(source_zone__name='MSP')
        self.assertEqual((msp.protocol, msp.remote_access, msp.port_mappings), ('rdp', True, ['tcp/3389']))
        s7 = Flow.objects.get(source_zone__name='Control room', destination_zone__name='Cell', protocol='s7comm')
        self.assertEqual(s7.access, ['read', 'control'])
        self.assertEqual(s7.first_seen.isoformat(), '2026-11-01T08:00:20+00:00')
        server = IndustrialService.objects.get(device=self.plc, protocol='s7comm', role='server')
        self.assertEqual(server.service.port_mappings, ['tcp/102'])
        # The unknown host in the cell comes first; the MSP laptop and the server are not in NetBox either
        self.assertEqual(rows[0]['ip'], '10.10.10.99')
        self.assertEqual((rows[0]['zone'], rows[0]['serves']), ('Cell', 'tcp/445'))
        self.assertEqual({r['ip'] for r in rows}, {'10.10.10.99', '10.10.30.2', '192.168.50.7'})
        self.assertIn('Observed hosts not in NetBox: 3 (3 inside a zone)', output)

    def test_unknown_import_files(self):
        """The bulk-import files load in NetBox's own import forms once a person named role and device type."""
        from dcim.forms import DeviceImportForm, InterfaceImportForm
        from dcim.models import Device
        from ipam.forms import IPAddressImportForm

        with tempfile.TemporaryDirectory() as tmp:
            write_logs(tmp)
            Path(tmp, 'zones.csv').write_text('192.168.50.0/24,MSP,,external\n10.10.30.0/24,Servers,3\n')
            out = StringIO()
            call_command('ot_import', tmp, '--site', 'plant', '--zone-map', str(Path(tmp, 'zones.csv')),
                         '--unknown-import', str(Path(tmp, 'import')), stdout=out)
            files = {p.name: list(csv.DictReader(p.open())) for p in sorted(Path(tmp, 'import').iterdir())}
        self.assertEqual(list(files), ['1-devices.csv', '2-interfaces.csv', '3-ip-addresses.csv'])
        # The MSP laptop is in an external zone: not a device of the plant
        self.assertEqual([d['name'] for d in files['1-devices.csv']], ['unknown-10.10.10.99', 'unknown-10.10.30.2'])
        device = files['1-devices.csv'][0]
        self.assertEqual((device['role'], device['device_type'], device['site']), ('', '', 'Plant'))
        self.assertIn('In zone Cell', device['description'])
        self.assertIn('serves tcp/445', device['description'])
        # The mask of the prefix NetBox has, else /32
        self.assertEqual([a['address'] for a in files['3-ip-addresses.csv']], ['10.10.10.99/24', '10.10.30.2/32'])
        self.assertIn('Bulk-import files for 2 unknown host(s)', out.getvalue())

        self.assertFalse(DeviceImportForm(device).is_valid())  # a person names what it is first
        known = self.plc
        for row in files['1-devices.csv']:
            row.update(role=known.role.name, manufacturer=known.device_type.manufacturer.name,
                       device_type=known.device_type.model)
        for form_class, name in ((DeviceImportForm, '1-devices.csv'), (InterfaceImportForm, '2-interfaces.csv'),
                                 (IPAddressImportForm, '3-ip-addresses.csv')):
            for row in files[name]:
                form = form_class(row)
                self.assertTrue(form.is_valid(), form.errors)
                form.save()
        created = Device.objects.get(name='unknown-10.10.10.99')
        self.assertEqual(str(created.primary_ip4), '10.10.10.99/24')

    def test_zeek_needs_zones(self):
        empty = Site.objects.create(name='Empty', slug='empty')
        with tempfile.TemporaryDirectory() as tmp:
            write_logs(tmp)
            with self.assertRaisesRegex(CommandError, 'No zone to place addresses in'):
                call_command('ot_import', tmp, '--site', empty.slug, stdout=StringIO())
            with self.assertRaisesRegex(CommandError, 'for Zeek logs'):
                call_command('ot_import', tmp, '--site', 'plant', '--format', 'observations',
                             '--zone-map', 'x.csv', stdout=StringIO())
