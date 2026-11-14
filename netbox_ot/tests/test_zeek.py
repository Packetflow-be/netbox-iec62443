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
            streams = zeek.read_logs(tmp)
            self.assertTrue(zeek.is_zeek_directory(tmp))
            # Nothing is read until a stream is iterated; a stream can be read again (opcua_binary is, twice)
            self.assertIsNone(streams['conn'].count)
            logs = {name: list(records) for name, records in streams.items()}
            self.assertEqual(list(streams['conn']), logs['conn'])
            self.assertEqual(streams['conn'].count, len(CONN))
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
        # An address line's level is that asset's level, not its zone's
        self.assertEqual((zones.levels, zones.address_levels, zones.types),
                         ({}, {'10.10.30.2': '3'}, {'MSP': 'external'}))
        Path(f.name).write_text('10.10.10.0/24,Cell,1\n10.10.10.20,Cell,2\n')
        zones = zeek.ZoneMap.from_csv(f.name)
        self.assertEqual((zones.levels, zones.address_levels), ({'Cell': '1'}, {'10.10.10.20': '2'}))
        Path(f.name).write_text('10.10.10.0/24,Cell,high\n')
        with self.assertRaisesRegex(ValueError, 'not a number'):
            zeek.ZoneMap.from_csv(f.name)
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


class PortScanTest(SimpleTestCase):
    """A scanner tries 120 ports on a PLC; three answer with data, one only completes the handshake."""

    def setUp(self):
        def conn(uid, src, port, state, history, data=10):
            return {'ts': T0, 'uid': uid, 'id.orig_h': src, 'id.resp_h': '10.10.10.10', 'id.resp_p': port,
                    'proto': 'tcp', 'service': None, 'conn_state': state, 'history': history,
                    'orig_bytes': data, 'resp_bytes': data}
        records = [conn(f'R{p}', '10.10.20.9', p, 'REJ', 'Sr', 0) for p in range(1000, 1120)]
        records += [conn('D1', '10.10.20.9', 80, 'SF', 'ShADadFf'), conn('D2', '10.10.20.9', 443, 'SF', 'ShADadFf'),
                    conn('D3', '10.10.20.9', 102, 'SF', 'ShADadFf'), conn('P1', '10.10.20.9', 8080, 'RSTO', 'ShR', 0)]
        # An ordinary client: a handshake without data to 8081 is a probe, its HTTP session is traffic
        records += [conn('P2', '10.10.20.5', 8081, 'RSTO', 'ShR', 0), conn('H1', '10.10.20.5', 80, 'SF', 'ShADadFf')]
        read = {'ts': T0, 'uid': 'D3', 'id.orig_h': '10.10.20.9', 'id.resp_h': '10.10.10.10', 'id.resp_p': 102,
                'is_orig': True, 'function_name': 'Read Variable'}
        logs = {'conn': records, 's7comm': [read]}
        self.assets, self.flows, self.summary = zeek.to_observations(logs, ZONES)

    def test_scan_is_reported_and_collapsed(self):
        self.assertEqual(self.summary['scans'], [{'ip': '10.10.20.9', 'from': 'Control room', 'to': 'Cell PLCs',
                                                  'ports': 124, 'hosts': 1}])
        scanner = sorted((f['proto'], f.get('port'), f.get('func', '')) for f in self.flows
                         if f['src'] == '10.10.20.9')
        # Its S7 read stays; everything else it reached is one request without a port
        self.assertEqual(scanner, [('port scan', None, ''), ('s7comm', 102, 'Read Variable')])
        self.assertEqual(next(f['count'] for f in self.flows if f['proto'] == 'port scan'), 2)
        client = sorted(f.get('port') for f in self.flows if f['src'] == '10.10.20.5')
        self.assertEqual(client, [80])  # the probe to 8081 is not traffic
        # Answered ports are open ports, probe or not
        plc = next(a for a in self.assets if a['ip'] == '10.10.10.10')
        self.assertEqual(plc['open_ports'], [80, 102, 443, 8080, 8081])

    def test_plan_names_the_scan(self):
        plan = build_plan(self.assets, self.flows, self.summary)
        flow = next(f for f in plan.flows if f.source == 'Control room' and not f.protocol)
        self.assertEqual(flow.port_mappings, ['tcp/80'])  # the ordinary client's session, none of the scanned ports
        self.assertIn('Port scan from 10.10.20.9: 124 TCP ports tried on 1 host(s)', flow.evidence)
        self.assertNotIn('Protocol not recognised: port scan', flow.evidence)
        self.assertIn('Protocol not recognised: tcp/80', flow.evidence)


class ZoneMapLevelsTest(SimpleTestCase):
    """The HMI and the PLC in one zone map network: the cell's traffic is reported, and --split makes it flows."""

    ZONES = zeek.ZoneMap(networks={'10.10.10.0/24': 'Cell', '10.10.20.0/24': 'Cell'}, levels={'Cell': '1'},
                         address_levels={'10.10.10.10': '1', '10.10.20.5': '2'})

    def setUp(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_logs(tmp)
            self.assets, self.flows, self.summary = zeek.to_observations(zeek.read_logs(tmp), self.ZONES)

    def test_levels_go_to_addresses_and_zones(self):
        levels = {a['ip']: a.get('purdue_level') for a in self.assets}
        self.assertEqual(levels['10.10.20.5'], '2')
        self.assertIsNone(levels['10.10.10.99'])  # the network's level is the zone's, not every asset's
        self.assertIn({'name': 'Cell', 'purdue_level': '1'}, self.summary['zones'])
        plan = build_plan(self.assets, self.flows, self.summary)
        self.assertEqual(plan.zones['Cell'].purdue_level, '1')
        self.assertNotIn('10.10.10.99', plan.asset_levels)

    def test_traffic_inside_a_zone_is_reported(self):
        from netbox_ot.importers.observations import inside_zone_advice
        plan = build_plan(self.assets, self.flows, self.summary)
        self.assertFalse([f for f in plan.flows if f.source == f.destination])
        cell = plan.inside['Cell']
        self.assertEqual((cell.requests, cell.modifying), (5, 2))  # Modbus 3 + S7comm 2; a write and PLC Stop
        self.assertEqual(cell.modifying_senders, {'10.10.20.5'})
        self.assertIn('--split "Cell"', inside_zone_advice(cell))

    def test_split_from_zone_map_levels(self):
        plan = build_plan(self.assets, self.flows, self.summary, split_zones=['Cell'])
        flows = {(f.source, f.destination, f.protocol) for f in plan.flows}
        self.assertIn(('Cell (supervisory)', 'Cell (control)', 's7comm'), flows)
        self.assertIn(('Cell (supervisory)', 'Cell (control)', 'modbus-tcp'), flows)
        self.assertEqual(plan.not_split, {})

    def test_why_a_zone_is_not_split(self):
        assets = [{k: v for k, v in a.items() if k != 'purdue_level'} for a in self.assets]
        plan = build_plan(assets, self.flows, self.summary, split_zones=['Cell', 'Nowhere'])
        self.assertEqual(plan.not_split, {'Cell': 'none of its assets has a Purdue level',
                                          'Nowhere': 'no asset of the input is in this zone'})


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
        self.assertIn('Zeek logs: conn (10), modbus (3), s7comm (3)', output)
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
        self.assertEqual((rows[0]['zone'], rows[0]['serves']), ('Cell', 'icmp, tcp/445'))  # ICMP has no port
        self.assertEqual({r['ip'] for r in rows}, {'10.10.10.99', '10.10.30.2', '192.168.50.7'})
        self.assertIn('Observed hosts not in NetBox: 3 (3 inside a zone)', output)

    def test_zone_level_is_not_copied_onto_devices(self):
        """A network line's level is the zone's; only an address line sets a device's Purdue level."""
        from netbox_ot.customfields import PURDUE_CF_NAME
        with tempfile.TemporaryDirectory() as tmp:
            write_logs(tmp)
            Path(tmp, 'zones.csv').write_text('10.10.20.0/24,Control room,1\n10.10.10.10,Cell,1\n')
            call_command('ot_import', tmp, '--site', 'plant', '--zone-map', str(Path(tmp, 'zones.csv')),
                         stdout=StringIO())
        self.hmi.refresh_from_db()
        self.plc.refresh_from_db()
        self.assertFalse(self.hmi.custom_field_data.get(PURDUE_CF_NAME))
        self.assertEqual(self.plc.custom_field_data.get(PURDUE_CF_NAME), '1')

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
        self.assertEqual([d['name'] for d in files['1-devices.csv']],
                         ['unknown-10.10.10.99-plant', 'unknown-10.10.30.2-plant'])
        device = files['1-devices.csv'][0]
        self.assertEqual((device['role'], device['device_type'], device['site']), ('', '', 'Plant'))
        self.assertIn('fill in role, manufacturer, device_type in 1-devices.csv (names as NetBox shows them',
                      out.getvalue())
        self.assertIn('In zone Cell', device['description'])
        self.assertIn('serves icmp, tcp/445', device['description'])
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
        created = Device.objects.get(name='unknown-10.10.10.99-plant')
        self.assertEqual(str(created.primary_ip4), '10.10.10.99/24')

    def test_unknown_import_for_a_second_plant(self):
        """A second plant on the same addresses: unique names, defaults for role and type, known addresses left out."""
        from dcim.forms import DeviceImportForm, InterfaceImportForm
        from dcim.models import Device
        from ipam.forms import IPAddressImportForm

        Site.objects.create(name='Plant 2', slug='plant-2')
        role, device_type = self.plc.role, self.plc.device_type
        with tempfile.TemporaryDirectory() as tmp:
            write_logs(tmp)
            Path(tmp, 'zones.csv').write_text('10.10.10.0/24,Cell,1,ot\n10.10.20.0/24,Control room,2,ot\n'
                                              '10.10.20.5,Control room,2,\n')
            out = StringIO()
            call_command('ot_import', tmp, '--site', 'plant-2', '--zone-map', str(Path(tmp, 'zones.csv')),
                         '--unknown-import', str(Path(tmp, 'import')), '--unknown-role', role.slug,
                         '--unknown-device-type', device_type.model, stdout=out)
            files = {p.name: list(csv.DictReader(p.open())) for p in sorted(Path(tmp, 'import').iterdir())}
            with self.assertRaisesRegex(CommandError, 'goes with --unknown-import'):
                call_command('ot_import', tmp, '--site', 'plant-2', '--unknown-role', role.slug, stdout=StringIO())
            with self.assertRaisesRegex(CommandError, 'not found in NetBox'):
                call_command('ot_import', tmp, '--site', 'plant-2', '--unknown-import', tmp,
                             '--unknown-device-type', 'nonexistent', stdout=StringIO())
        devices = {d['name']: d for d in files['1-devices.csv']}
        self.assertEqual(sorted(devices), ['unknown-10.10.10.10-plant-2', 'unknown-10.10.10.99-plant-2',
                                           'unknown-10.10.20.5-plant-2'])
        hmi = devices['unknown-10.10.20.5-plant-2']
        self.assertEqual((hmi['role'], hmi['manufacturer'], hmi['device_type'], hmi['cf_ot_purdue_level']),
                         (role.name, device_type.manufacturer.name, device_type.model, '2'))
        self.assertNotIn('fill in', out.getvalue())
        # The global table already holds the first plant's PLC and HMI addresses: left out, with the advice
        self.assertEqual([a['address'] for a in files['3-ip-addresses.csv']], ['10.10.10.99/24'])
        self.assertIn('2 address(es) already exist in the global table', out.getvalue())
        self.assertIn('10.10.20.5: 10.10.20.5/24 on hmi-1', out.getvalue())
        self.assertIn('Give each plant its own VRF and import with --vrf', out.getvalue())
        # The files load as they are; the interface import finds the device of this plant, not of the first one
        for form_class, name in ((DeviceImportForm, '1-devices.csv'), (InterfaceImportForm, '2-interfaces.csv'),
                                 (IPAddressImportForm, '3-ip-addresses.csv')):
            for row in files[name]:
                form = form_class(row)
                self.assertTrue(form.is_valid(), (name, form.errors))
                form.save()
        created = Device.objects.get(name='unknown-10.10.20.5-plant-2')
        self.assertEqual((created.site.slug, created.custom_field_data.get('ot_purdue_level')), ('plant-2', '2'))

    def test_zeek_needs_zones(self):
        empty = Site.objects.create(name='Empty', slug='empty')
        with tempfile.TemporaryDirectory() as tmp:
            write_logs(tmp)
            # A first visit shows the networks of the capture and points at --suggest-zone-map
            out = StringIO()
            with self.assertRaisesRegex(CommandError, 'No zone to place these addresses in yet.*--suggest-zone-map'):
                call_command('ot_import', tmp, '--site', empty.slug, stdout=out)
            self.assertIn('10.10.10.0/24        2 host(s)        4 connection(s), in no zone; serves modbus (1), '
                          's7comm (1), tcp/445 (1)', out.getvalue())
            with self.assertRaisesRegex(CommandError, 'for Zeek logs'):
                call_command('ot_import', tmp, '--site', 'plant', '--format', 'observations',
                             '--zone-map', 'x.csv', stdout=StringIO())

    def test_suggest_zone_map(self):
        empty = Site.objects.create(name='Empty', slug='empty')
        with tempfile.TemporaryDirectory() as tmp:
            write_logs(tmp)
            draft = Path(tmp, 'draft.csv')
            out = StringIO()
            call_command('ot_import', tmp, '--site', empty.slug, '--suggest-zone-map', str(draft), stdout=out)
            self.assertIn('Draft zone map with 4 network(s)', out.getvalue())
            self.assertFalse(Zone.objects.filter(site=empty).exists())  # nothing imported
            lines = [line for line in draft.read_text().splitlines() if not line.startswith('#')]
            self.assertEqual(lines, ['network,zone,purdue_level,type', '10.10.10.0/24,10.10.10.0/24,,',
                                     '10.10.20.0/24,10.10.20.0/24,,', '10.10.30.0/24,10.10.30.0/24,,',
                                     '192.168.50.0/24,192.168.50.0/24,,'])
            self.assertIn('# 10.10.20.0/24: 1 host(s), 1 connection(s); serves rdp (1)', draft.read_text())
            # The draft is a valid zone map as it stands
            self.assertEqual(zeek.ZoneMap.from_csv(draft).zone_of('10.10.10.10'), '10.10.10.0/24')
            # With zones in NetBox only the networks no zone holds are left
            call_command('ot_import', tmp, '--site', 'plant', '--suggest-zone-map', str(draft), stdout=StringIO())
            lines = [line.split(',')[0] for line in draft.read_text().splitlines() if not line.startswith('#')]
            self.assertNotIn('10.10.10.0/24', lines)
