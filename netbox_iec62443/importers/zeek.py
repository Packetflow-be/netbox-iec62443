"""
Zeek adapter: turns a directory of Zeek logs (with or without the CISA ICSNPP parsers, as Zeek or Malcolm write
them) into the plugin's observation format (assets, flows, summary), which build_plan() and apply_plan() then
import like any other source. No database access here: zones come in as a ZoneMap.

  logs      *.log and *.log.gz, Zeek TSV or JSON lines, rotated files included (conn.00:00:00-01:00:00.log.gz).
            The stream name is the file name up to the first dot.
  requests  from the protocol logs listed in STREAMS: one per request (responses are skipped), from the
            connection's originator to its responder (id.orig_h -> id.resp_h, port id.resp_p), with the function
            the parser names (Modbus function, S7 function, CIP service, DNP3 function code, ...).
  conn.log  connections whose uid has no protocol-log request: the protocol Zeek identified from the payload
            (the "service" field: rdp, ssh, ssl, modbus, ...), or else "tcp/<port>" (not identified; no protocol
            is guessed from the port). TCP attempts that were never answered (S0, REJ, ...) are skipped; one-way
            UDP counts. Answered TCP ports become the responder's open ports.
  assets    every IPv4 address seen that the zone map places in a zone. Others go to the outside zone.

Multicast and broadcast destinations are skipped, as are IPv6 addresses (the import format is IPv4).
"""
import gzip
import ipaddress
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .observations import protocol_value

# Protocol logs: stream -> (protocol name for the importer, function fields in order of preference,
# how to tell a request: (field, values) or None when every record is a request)
STREAMS = {
    'modbus': ('modbus', ('func',), None),
    'modbus_detailed': ('modbus', ('func',), ('request_response', ('REQUEST',))),
    'modbus_read_write_multiple_registers': ('modbus', ('func',), ('request_response', ('REQUEST',))),
    'modbus_mask_write_register': ('modbus', ('func',), ('request_response', ('REQUEST',))),
    's7comm': ('s7comm', ('function_name', 'subfunction_name', 'rosctr_name'), ('is_orig', ('T', True))),
    's7comm_plus': ('s7comm-plus', ('function_name', 'opcode_name'), ('is_orig', ('T', True))),
    'cip': ('cip', ('cip_service',), ('direction', ('request',))),
    'enip': ('enip', ('enip_command',), ('is_orig', ('T', True))),
    'dnp3': ('dnp3', ('fc_request',), None),
    'dnp3_control': ('dnp3', ('function_code',), ('is_orig', ('T', True))),
    'bacnet': ('bacnet', ('pdu_service',), ('is_orig', ('T', True))),
    'bacnet_property': ('bacnet', ('pdu_service',), ('is_orig', ('T', True))),
    'bacnet_device_control': ('bacnet', ('pdu_service',), ('is_orig', ('T', True))),
    'opcua_binary': ('opcua', ('req_identifier_str',), None),
    'omron_fins_general': ('fins', ('command_code',), ('icf_data_type', ('Command (0)',))),
    'hart_ip_general': ('hart-ip', (), None),
    'profinet_io_cm': ('profinet', ('operation_type',), None),
}
# conn.log states of a TCP connection that was answered
ANSWERED = {'SF', 'S1', 'S2', 'S3', 'RSTO', 'RSTR'}
UNSET = ('-', '(empty)', '', None)


def _open(path):
    return gzip.open(path, 'rt', encoding='utf-8', errors='replace') if path.suffix == '.gz' else \
        path.open(encoding='utf-8', errors='replace')


def _flatten(record, prefix=''):
    flat = {}
    for key, value in record.items():
        if isinstance(value, dict):
            flat.update(_flatten(value, f'{prefix}{key}.'))
        else:
            flat[f'{prefix}{key}'] = value
    return flat


def read_log(path):
    """Records of one Zeek log file (TSV or JSON lines) as flat dicts; unset values are None."""
    with _open(Path(path)) as f:
        fields, separator = None, '\t'
        for line in f:
            line = line.rstrip('\n')
            if not line:
                continue
            if line.startswith('{'):
                try:
                    yield {k: (None if v in UNSET else v) for k, v in _flatten(json.loads(line)).items()}
                except ValueError:
                    continue
            elif line.startswith('#separator'):
                separator = line.split(' ', 1)[1].encode().decode('unicode_escape')
            elif line.startswith('#fields'):
                fields = line.split(separator)[1:]
            elif line.startswith('#'):
                continue
            elif fields:
                values = line.split(separator)
                yield {k: (None if v in UNSET else v) for k, v in zip(fields, values)}


def read_logs(directory):
    """{stream: [records]} for the Zeek logs in `directory`."""
    logs = defaultdict(list)
    for path in sorted(Path(directory).iterdir()):
        if path.is_file() and (path.name.endswith('.log') or path.name.endswith('.log.gz')):
            logs[path.name.split('.')[0]].extend(read_log(path))
    return dict(logs)


def is_zeek_directory(directory):
    return any(Path(directory).glob('conn.*log*')) or any(Path(directory).glob('conn.log'))


def _ts(value):
    """Zeek time (epoch seconds or ISO 8601) as an aware datetime, or None."""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def _ipv4(value):
    try:
        ip = ipaddress.ip_address(value)
    except (TypeError, ValueError):
        return None
    return ip if ip.version == 4 else None


OPCUA_MESSAGES = {'HEL': 'Hello', 'ACK': 'Acknowledge', 'OPN': 'OpenSecureChannel', 'CLO': 'CloseSecureChannel'}


def _function(record, fields):
    """The first function field that is set; 'Run (0x0401)' becomes 'Run'."""
    if record.get('msg_type') in OPCUA_MESSAGES and not record.get('req_identifier_str'):
        return OPCUA_MESSAGES[record['msg_type']]
    for name in fields:
        value = record.get(name)
        if value not in UNSET:
            value = str(value)
            for prefix in ('Request: ', 'Response: '):
                value = value[len(prefix):] if value.startswith(prefix) else value
            return value.split(' (0x')[0].strip() if ' (0x' in value else value
    return ''


class ZoneMap:
    """
    Which zone an address belongs to: an exact address (a zone member's primary IP) first, then the most
    specific network. `networks` and `addresses` are {network or address: zone name}; `levels` and `types` are
    optional {zone name: Purdue level / zone type} for zones the import may create.
    """

    def __init__(self, networks=None, addresses=None, levels=None, types=None):
        self.networks = sorted(((ipaddress.ip_network(n), z) for n, z in (networks or {}).items()),
                               key=lambda item: -item[0].prefixlen)
        self.addresses = {ipaddress.ip_address(a): z for a, z in (addresses or {}).items()}
        self.levels = levels or {}
        self.types = types or {}

    def zone_of(self, ip):
        ip = ipaddress.ip_address(ip)
        if ip in self.addresses:
            return self.addresses[ip]
        for network, zone in self.networks:
            if ip in network:
                return zone
        return None

    def is_broadcast(self, ip):
        ip = ipaddress.ip_address(ip)
        return any(ip == network.broadcast_address and network.prefixlen < 31 for network, _zone in self.networks)

    @classmethod
    def from_csv(cls, path, base=None):
        """A zone map file: network or address, zone name, optional Purdue level, optional zone type."""
        import csv
        networks = dict(base.networks_dict()) if base else {}
        addresses = dict(base.addresses_dict()) if base else {}
        levels = dict(base.levels) if base else {}
        types = dict(base.types) if base else {}
        with open(path, newline='', encoding='utf-8') as f:
            for i, row in enumerate(csv.reader(f), start=1):
                if not row or row[0].strip().startswith('#') or row[0].strip().lower() in ('network', 'cidr'):
                    continue
                if len(row) < 2 or not row[1].strip():
                    raise ValueError(f'{path} line {i}: expected "network,zone[,purdue_level][,type]"')
                target, zone = row[0].strip(), row[1].strip()
                try:
                    if '/' in target:
                        networks[str(ipaddress.ip_network(target, strict=False))] = zone
                    else:
                        addresses[str(ipaddress.ip_address(target))] = zone
                except ValueError:
                    raise ValueError(f'{path} line {i}: {target!r} is not an address or network')
                if len(row) > 2 and row[2].strip():
                    levels[zone] = row[2].strip()
                if len(row) > 3 and row[3].strip():
                    types[zone] = row[3].strip()
        return cls(networks, addresses, levels, types)

    def networks_dict(self):
        return {str(n): z for n, z in self.networks}

    def addresses_dict(self):
        return {str(a): z for a, z in self.addresses.items()}


def to_observations(logs, zone_map, captures=None):
    """
    Zeek logs ({stream: [records]}) to the observation format: (assets, flows, summary). `zone_map` places
    addresses in zones; `captures` names the capture(s) in the evidence.
    """
    requests = defaultdict(lambda: {'count': 0, 'first': None, 'last': None})
    covered = set()  # connection uids that have protocol-log requests
    open_ports = defaultdict(set)
    seen = set()
    times = []

    def keep(src, dst):
        return src and dst and not dst.is_multicast and dst != ipaddress.IPv4Address('255.255.255.255') \
            and not zone_map.is_broadcast(dst)

    def add(src, dst, proto, port, transport, func, ts):
        key = (str(src), str(dst), proto, port, transport, func)
        entry = requests[key]
        entry['count'] += 1
        if ts:
            entry['first'] = min(entry['first'], ts) if entry['first'] else ts
            entry['last'] = max(entry['last'], ts) if entry['last'] else ts
            times.append(ts)
        seen.update((str(src), str(dst)))

    for stream, (proto, func_fields, request) in STREAMS.items():
        for record in logs.get(stream, []):
            if request is not None:
                field, values = request
                if record.get(field) not in values:
                    continue
            src, dst = _ipv4(record.get('id.orig_h')), _ipv4(record.get('id.resp_h'))
            if not keep(src, dst):
                continue
            port = record.get('id.resp_p')
            add(src, dst, proto, int(port) if port and str(port).isdigit() else None, record.get('proto'),
                _function(record, func_fields), _ts(record.get('ts')))
            if record.get('uid'):
                covered.add(record['uid'])

    zone_pairs = defaultdict(int)
    for record in logs.get('conn', []):
        src, dst = _ipv4(record.get('id.orig_h')), _ipv4(record.get('id.resp_h'))
        if not keep(src, dst):
            continue
        transport = record.get('proto')
        if transport == 'tcp' and record.get('conn_state') not in ANSWERED:
            continue
        port = record.get('id.resp_p')
        port = int(port) if port and str(port).isdigit() else None
        ts = _ts(record.get('ts'))
        if ts:
            times.append(ts)
        zone_pairs[(zone_map.zone_of(src), zone_map.zone_of(dst))] += 1
        if transport == 'tcp' and port:
            open_ports[str(dst)].add(port)
        if record.get('uid') in covered:
            continue
        services = [s.strip() for s in (record.get('service') or '').split(',') if s.strip()]
        service = next((s for s in services if protocol_value(s)), services[0] if services else '')
        proto = service or (f'{transport}/{port}' if port else transport or 'ip')
        add(src, dst, proto, port, transport if transport in ('tcp', 'udp') else None, '', ts)

    assets = []
    for ip in sorted(seen, key=ipaddress.ip_address):
        zone = zone_map.zone_of(ip)
        if zone:
            asset = {'ip': ip, 'zone': zone}
            if zone_map.levels.get(zone) not in (None, ''):
                asset['purdue_level'] = zone_map.levels[zone]
            if open_ports.get(ip):
                asset['open_ports'] = sorted(open_ports[ip])
            assets.append(asset)
    flows = []
    for (src, dst, proto, port, transport, func), entry in requests.items():
        flow = {'src': src, 'dst': dst, 'proto': proto, 'count': entry['count']}
        if func:
            flow['func'] = func
        if port:
            flow['port'] = port
            if transport in ('tcp', 'udp'):
                flow['transport'] = transport
        if entry['first']:
            flow['first_seen'] = entry['first'].isoformat()
            flow['last_seen'] = entry['last'].isoformat()
        flows.append(flow)
    summary = {
        'captures': list(captures or []),
        'zone_pairs': [{'from': a or '', 'to': b or '', 'count': n} for (a, b), n in zone_pairs.items() if a != b],
        'zones': [{'name': z, 'type': t} for z, t in zone_map.types.items()],
    }
    if times:
        start, end = min(times), max(times)
        summary.update(start=start.isoformat(), end=end.isoformat(),
                       hours=round((end - start).total_seconds() / 3600, 1))
    return assets, flows, summary
