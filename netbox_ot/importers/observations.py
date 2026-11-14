"""
Importer for observation files: what was seen on an OT network, in the plugin's documented import format
(docs/import-format.md): assets.json, flows.json and optionally summary.json. Any tool can write them:
a script over Zeek/ICSNPP or Malcolm logs, an asset-discovery export, or a spreadsheet.

One import covers one site and one routing domain (the global table or one VRF). Duplicate machine
networks are normal in OT, so every lookup in NetBox is scoped to that site and VRF.

  zones     one per zone name in assets.json. A zone that mixes controllers (Purdue 0-1) with supervisory
            assets (2) or site operations (3+) can be split into one zone per band, e.g. "Cell A (control)"
            and "Cell A (supervisory)", so the paths between them become flows. Splitting is opt-in: per
            zone (`split_zones`) or every mixed zone (True). Purdue level = the lowest level among the zone's
            assets. Addresses not in assets.json fall into one external zone without a Purdue level
            (`outside_zone`). A new zone's type comes from summary.json "zones", else from its level.
  prefixes  the most specific prefix NetBox already has for each asset's address, in the site and VRF.
            The importer never creates prefixes, and does not link a prefix that holds assets of two zones.
  flows     one per source zone, destination zone and protocol, from the OT requests between zones; pairs from
            summary.json "zone_pairs" without any identified request become one flow without a protocol.
            ports = the destination ports the input gives (none are assumed); access = what the requests do
            (read, write, control, program; see functions.py); remote_access = an asset marked `remote_access`
            sent requests on it, or the source zone is external; first/last seen = the requests' times, else the
            capture window; evidence = counts and the request lines with their class. A request may come
            through a broker (`connection` "brokered", `broker` = its address: the flow gets the broker's zone
            and the topics) or over a connection its destination opened ("reverse-connect"); flows are kept
            apart per connection model. A flow joins the conduit that is the only one joining its zones (and
            the broker zone); otherwise its conduit is left for a person to set.
  devices   matched by primary IPv4 within the site and VRF; an address that matches more than one device or
            VM is skipped and reported. Matched assets get the zone membership and their Purdue level.
  services  industrial services per asset: a server for every protocol it answered or that assets.json names
            in its "services", a client for every protocol it sent requests in. A server whose port is known is
            linked to a NetBox application service with that port (found or created). An open port alone does
            not say which protocol listens there (port 102 is S7comm or IEC 61850 MMS), so it creates nothing;
            open OT ports that no identified service explains are listed in the plan for a person to resolve.

Re-running is safe: it adds members, ports and access classes, widens first/last seen and refreshes evidence,
but never overwrites a human decision (a flow's verdict, conduit or hops; a zone's or device's Purdue level).
"""
import ipaddress
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from django.utils.text import slugify

from ..choices import ConnectionChoices, FlowProtocolChoices, IndustrialProtocolChoices, ZoneTypeChoices
from .functions import CLASSES, MODIFYING, UNCLASSIFIED, classify

# Protocol names in the analysis output (Zeek/ICSNPP, tshark) -> plugin protocol values
PROTOCOL_NAMES = {
    's7comm': 's7comm', 's7comm-plus': 's7comm-plus', 's7comm_plus': 's7comm-plus', 'modbus': 'modbus-tcp',
    'modbus/tcp': 'modbus-tcp', 'enip': 'ethernet-ip', 'ethernet/ip': 'ethernet-ip', 'cip': 'ethernet-ip',
    'dnp3': 'dnp3', 'bacnet': 'bacnet-ip', 'bacnet/ip': 'bacnet-ip', 'opcua': 'opc-ua', 'opc ua': 'opc-ua',
    'opcua-binary': 'opc-ua', 'opcua_binary': 'opc-ua', 'iec104': 'iec-104', 'iec-104': 'iec-104',
    'iec 60870-5-104': 'iec-104', 'mms': 'iec-61850-mms', 'iec61850': 'iec-61850-mms', 'goose': 'iec-61850-goose',
    'profinet': 'profinet', 'profinet_io_cm': 'profinet', 'mqtt': 'mqtt', 'hart-ip': 'hart-ip', 'hart_ip': 'hart-ip',
    'omron fins': 'omron-fins', 'fins': 'omron-fins',
    'rdp': 'rdp', 'ssh': 'ssh', 'telnet': 'telnet', 'vnc': 'vnc', 'rfb': 'vnc', 'http': 'http', 'https': 'https',
    'ssl': 'https', 'smb': 'smb', 'dns': 'dns', 'ntp': 'ntp', 'snmp': 'snmp', 'syslog': 'syslog',
}
# Well-known OT ports -> the protocols that use them. Only used to report open ports that no identified
# service explains; a port never decides the protocol. OPC DA (DCOM, 135) is left out: every Windows host has it.
OT_PORTS = defaultdict(list)
for _protocol, _ports in IndustrialProtocolChoices.DEFAULT_PORTS.items():
    if _protocol != IndustrialProtocolChoices.OPC_DA:
        for _port in _ports:
            OT_PORTS[_port].append(_protocol)
OT_PORTS = dict(OT_PORTS)
BANDS = ('control', 'supervisory', 'operations')
LISTENING = ('server', 'both')
EVIDENCE_LINES = 50  # request lines kept in a flow's evidence, largest counts first


@dataclass
class ZonePlan:
    name: str
    slug: str
    zone_type: str = ZoneTypeChoices.OT
    purdue_level: str = ''
    description: str = ''
    member_ips: list = field(default_factory=list)


@dataclass
class FlowPlan:
    name: str
    source: str
    destination: str
    protocol: str = ''
    port_mappings: list = field(default_factory=list)
    access: list = field(default_factory=list)
    remote_access: bool = False
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    evidence: str = ''
    connection: str = ConnectionChoices.CLIENT_SERVER
    broker_zone: str = ''  # zone name, for a flow through a broker
    topics: list = field(default_factory=list)


@dataclass
class ServicePlan:
    ip: str
    protocol: str
    role: str
    port_mappings: list = field(default_factory=list)
    evidence: list = field(default_factory=list)


@dataclass
class OpenPort:
    """An open OT port that no identified service on the asset explains."""
    ip: str
    port: int
    candidates: list  # protocol values that commonly use this port


@dataclass
class HostPlan:
    """What was seen of one address, for the report of observed hosts that NetBox does not know."""
    ip: str
    zone: str = ''  # '' when the address is outside the observed zones
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    peers: set = field(default_factory=set)
    serves: set = field(default_factory=set)  # protocols (and ports) it answered
    uses: set = field(default_factory=set)  # protocols it sent requests in
    open_ports: set = field(default_factory=set)


@dataclass
class ImportPlan:
    zones: dict
    flows: list
    asset_levels: dict  # ip -> Purdue level string
    services: list = field(default_factory=list)
    unidentified_ports: list = field(default_factory=list)
    hosts: dict = field(default_factory=dict)  # ip -> HostPlan


@dataclass
class _Request:
    src: str
    dst: str
    proto: str  # as written in the input
    protocol: str  # plugin protocol value, '' if not recognised
    func: str
    count: int
    access: str  # functions.READ ... UNCLASSIFIED
    port_mapping: str  # 'tcp/102', or '' when the input gives no port
    first_seen: datetime | None
    last_seen: datetime | None
    connection: str = ConnectionChoices.CLIENT_SERVER
    broker: str = ''  # broker address, for a request through a broker
    topic: str = ''

    @property
    def line(self):
        port = f' {self.port_mapping}' if self.port_mapping else ''
        via = f' via broker {self.broker}' if self.broker else ''
        via += ' (reverse connect)' if self.connection == ConnectionChoices.REVERSE_CONNECT else ''
        topic = f' {self.topic}' if self.topic else ''
        line = f'{self.src} -> {self.dst}{via}{port} {self.proto} {self.func}{topic} x{self.count} [{self.access}]'
        return line.replace('  ', ' ')


def protocol_value(name):
    """Plugin protocol value for a protocol name from the input, or ''."""
    name = str(name)
    if name in FlowProtocolChoices.values():
        return name
    return PROTOCOL_NAMES.get(name.lower(), '')


def _timestamp(value, where):
    if value in (None, ''):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        raise ValueError(f'{where}: {value!r} is not an ISO 8601 date/time')
    if parsed.tzinfo is None:
        from django.utils import timezone
        parsed = timezone.make_aware(parsed)
    return parsed


def _port_mapping(port, transport, protocol):
    if not port:
        return ''
    return f"{transport or FlowProtocolChoices.TRANSPORT.get(protocol, 'tcp')}/{port}"


def validate(assets, flows, summary):
    """Raise ValueError with the offending entry if the input does not follow docs/import-format.md."""
    def ip(value, where):
        try:
            ipaddress.IPv4Address(value)
        except (ipaddress.AddressValueError, ValueError, TypeError):
            raise ValueError(f'{where}: {value!r} is not an IPv4 address')

    def port(value, where):
        if not (isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 65535):
            raise ValueError(f'{where}: port {value!r} is not a TCP/UDP port')

    if not isinstance(assets, list) or not isinstance(flows, list) or not isinstance(summary, dict):
        raise ValueError('assets.json and flows.json hold a list, summary.json an object')
    seen = set()
    for i, a in enumerate(assets):
        where = f'assets.json[{i}]'
        if not isinstance(a, dict) or 'ip' not in a or not a.get('zone'):
            raise ValueError(f'{where}: "ip" and "zone" are required')
        ip(a['ip'], where)
        if a['ip'] in seen:
            raise ValueError(f'{where}: {a["ip"]} is listed twice')
        seen.add(a['ip'])
        if a.get('purdue_level') not in (None, ''):
            try:
                float(a['purdue_level'])
            except (TypeError, ValueError):
                raise ValueError(f'{where}: purdue_level {a["purdue_level"]!r} is not a number')
        if not isinstance(a.get('remote_access', False), bool):
            raise ValueError(f'{where}: remote_access is true or false')
        for j, s in enumerate(a.get('services') or []):
            if not isinstance(s, dict) or not protocol_value(s.get('proto', '')):
                raise ValueError(f'{where}.services[{j}]: "proto" must be a known protocol')
            if 'port' in s:
                port(s['port'], f'{where}.services[{j}]')
            if s.get('transport') not in (None, 'tcp', 'udp'):
                raise ValueError(f'{where}.services[{j}]: transport is "tcp" or "udp"')
    for i, f in enumerate(flows):
        where = f'flows.json[{i}]'
        if not isinstance(f, dict) or not all(f.get(k) for k in ('src', 'dst', 'proto')):
            raise ValueError(f'{where}: "src", "dst" and "proto" are required')
        ip(f['src'], where)
        ip(f['dst'], where)
        if f.get('access') not in (None, '') and str(f['access']).lower() not in CLASSES:
            raise ValueError(f'{where}: access {f["access"]!r} is not one of {", ".join(CLASSES)}')
        if 'port' in f:
            port(f['port'], where)
        if f.get('transport') not in (None, 'tcp', 'udp'):
            raise ValueError(f'{where}: transport is "tcp" or "udp"')
        connection = f.get('connection') or ConnectionChoices.CLIENT_SERVER
        if connection not in ConnectionChoices.values():
            raise ValueError(f'{where}: connection is one of {", ".join(ConnectionChoices.values())}')
        if connection == ConnectionChoices.BROKERED:
            if not f.get('broker'):
                raise ValueError(f'{where}: a request through a broker names the "broker" address')
            ip(f['broker'], where)
        elif f.get('broker'):
            raise ValueError(f'{where}: "broker" goes with connection "brokered"')
        if f.get('topic') is not None and not isinstance(f['topic'], str):
            raise ValueError(f'{where}: topic is a string')
        _timestamp(f.get('first_seen'), where)
        _timestamp(f.get('last_seen'), where)
    _timestamp(summary.get('start'), 'summary.json start')
    _timestamp(summary.get('end'), 'summary.json end')
    for i, z in enumerate(summary.get('zones') or []):
        if not isinstance(z, dict) or not z.get('name') or z.get('type') not in ZoneTypeChoices.values():
            raise ValueError(f'summary.json zones[{i}]: "name" and a "type" of '
                             f'{", ".join(ZoneTypeChoices.values())} are required')


def _level(value):
    if value is None or value == '':
        return ''
    value = float(value)
    return str(int(value)) if value.is_integer() else str(value)


def _band(level):
    """Purdue band of an asset: control (0-1), supervisory (2), operations (3 and up), or None."""
    if level is None or level == '':
        return None
    level = float(level)
    return BANDS[0] if level <= 1 else BANDS[1] if level <= 2 else BANDS[2]


def _zone_type(level, declared):
    """A new zone's type: as declared in summary.json, else 3.5 is a DMZ, 4 and 5 enterprise, the rest OT."""
    if declared:
        return declared
    if level == '3.5':
        return ZoneTypeChoices.DMZ
    if level and float(level) >= 4:
        return ZoneTypeChoices.ENTERPRISE
    return ZoneTypeChoices.OT


def build_plan(assets, flows, summary, outside_zone='Outside', split_zones=None):
    """
    Turn observation files into zones, flows, services and per-asset Purdue levels. No database access.

    outside_zone  name of the zone for addresses that are not in assets.json
    split_zones   zone names to split per Purdue band, or True for every mixed zone
    """
    validate(assets, flows, summary)
    by_ip = {a['ip']: a for a in assets}
    base_of_ip = {a['ip']: a['zone'] for a in assets}
    declared_types = {z['name']: z['type'] for z in summary.get('zones') or []}

    bands = defaultdict(set)
    for a in assets:
        bands[a['zone']].add(_band(a.get('purdue_level')))
    wanted = set(bands) if split_zones is True else set(split_zones or ())
    split = {z for z, b in bands.items() if z in wanted and len(b - {None}) > 1}

    def zone_of(ip):
        if ip not in by_ip:
            return outside_zone
        base, band = base_of_ip[ip], _band(by_ip[ip].get('purdue_level'))
        return f'{base} ({band})' if base in split and band else base

    def base_name(name):
        return name if name in bands else outside_zone

    zones, base_of_zone = {}, {}
    for a in assets:
        name = zone_of(a['ip'])
        z = zones.setdefault(name, ZonePlan(name=name, slug=slugify(name)))
        base_of_zone[name] = base_of_ip[a['ip']]
        z.member_ips.append(a['ip'])
    for name, z in zones.items():
        levels = [float(by_ip[ip]['purdue_level']) for ip in z.member_ips
                  if by_ip[ip].get('purdue_level') not in (None, '')]
        z.purdue_level = _level(min(levels)) if levels else ''
        z.zone_type = _zone_type(z.purdue_level, declared_types.get(name) or declared_types.get(base_of_zone[name]))
    # The most critical part of each split zone gets traffic that can't be pinned to one part
    critical = {}
    for name, z in zones.items():
        base = base_of_zone[name]
        if base in split and z.purdue_level and (
                base not in critical or float(z.purdue_level) < float(zones[critical[base]].purdue_level)):
            critical[base] = name

    def ensure_outside():
        if outside_zone not in zones:
            zones[outside_zone] = ZonePlan(
                name=outside_zone, slug=slugify(outside_zone),
                zone_type=declared_types.get(outside_zone, ZoneTypeChoices.EXTERNAL),
                description='Addresses not listed in the observations',
            )
            base_of_zone[outside_zone] = outside_zone

    captures = ', '.join(summary.get('captures', []))
    hours = summary.get('hours')
    seen_in = (f"captures {captures}" if captures else 'the observations') + (f" ({hours} h)" if hours else '')
    window = (_timestamp(summary.get('start'), ''), _timestamp(summary.get('end'), ''))

    requests = []
    for i, f in enumerate(flows):
        protocol = protocol_value(f['proto'])
        access = str(f.get('access') or '').lower() or classify(protocol, f.get('func'))
        requests.append(_Request(
            src=f['src'], dst=f['dst'], proto=str(f['proto']), protocol=protocol, func=str(f.get('func') or ''),
            count=f.get('count', 1), access=access,
            port_mapping=_port_mapping(f.get('port'), f.get('transport'), protocol),
            first_seen=_timestamp(f.get('first_seen'), '') or window[0],
            last_seen=_timestamp(f.get('last_seen'), '') or window[1],
            connection=f.get('connection') or ConnectionChoices.CLIENT_SERVER, broker=f.get('broker') or '',
            topic=str(f.get('topic') or ''),
        ))

    # OT requests between zones, keyed by (source zone, destination zone, protocol, connection, broker zone)
    ot = defaultdict(list)
    for r in requests:
        zs, zd = zone_of(r.src), zone_of(r.dst)
        if zs != zd:
            ot[(zs, zd, r.protocol, r.connection, zone_of(r.broker) if r.broker else '')].append(r)
    ot_pairs = {(key[0], key[1]) for key in ot}

    # Connection counts per directed zone pair, from zone_pairs
    headers = {}  # (src, dst) -> the zone pair's line: all traffic between the two zones, not one flow's
    for pair in summary.get('zone_pairs', []):
        src, dst, count = base_name(pair['from']), base_name(pair['to']), pair['count']
        if src == dst:
            continue
        line = f"All traffic from {src} to {dst}: {count} connection(s) in {seen_in}."
        if src in split or dst in split:
            keys = [k for k in ot_pairs if (base_of_zone.get(k[0], outside_zone), base_of_zone.get(k[1], outside_zone))
                    == (src, dst)]
            if not keys:
                keys = [(critical.get(src, src), critical.get(dst, dst))]
        else:
            keys = [(src, dst)]
        for key in keys:
            headers.setdefault(key, line)

    keys = list(ot) + [(s, d, '', ConnectionChoices.CLIENT_SERVER, '') for s, d in headers if (s, d) not in ot_pairs]
    plans = []
    for key in keys:
        src, dst, protocol, connection, broker_zone = key
        for name in (src, dst, broker_zone):
            if name == outside_zone:
                ensure_outside()
        crossing = sorted(ot.get(key, []), key=lambda r: -r.count)
        # The flow's own count first; the zone pair's total (every protocol between the two zones) after it
        if crossing:
            lines = [f'Passively seen: {sum(r.count for r in crossing)} request(s) on this flow in {seen_in}.']
            if (src, dst) in headers:
                lines.append(headers[(src, dst)])
        else:
            lines = [f'Passively seen: no identified request. {headers[(src, dst)]}']
        if connection == ConnectionChoices.BROKERED:
            brokers = ', '.join(dict.fromkeys(r.broker for r in crossing))
            lines.append(f'Through the broker {brokers} in {broker_zone}: {src} publishes, {dst} subscribes.')
        elif connection == ConnectionChoices.REVERSE_CONNECT:
            lines.append(f'Reverse connect: {dst} opens the connection, {src} sends the requests.')
        lines += [f'Request: {r.line}' for r in crossing[:EVIDENCE_LINES]]
        if len(crossing) > EVIDENCE_LINES:
            lines.append(f'... and {len(crossing) - EVIDENCE_LINES} more request lines')
        senders = list(dict.fromkeys(r.src for r in crossing if r.access in MODIFYING))
        if senders:
            lines.append('Changes the destination (write/control/program): ' + '; '.join(
                f"{by_ip.get(ip, {}).get('role') or 'unknown'} ({ip})" for ip in senders))
        unknown = sorted({r.proto for r in crossing if not r.protocol})
        if unknown:
            lines.append(f"Protocol not recognised: {', '.join(unknown)}")
        times_first = [r.first_seen for r in crossing if r.first_seen] or [t for t in [window[0]] if t]
        times_last = [r.last_seen for r in crossing if r.last_seen] or [t for t in [window[1]] if t]
        plans.append(FlowPlan(
            name=_flow_name(src, dst, protocol, connection, broker_zone), source=src, destination=dst,
            protocol=protocol, connection=connection, broker_zone=broker_zone,
            topics=list(dict.fromkeys(r.topic for r in crossing if r.topic)),
            port_mappings=list(dict.fromkeys(r.port_mapping for r in crossing if r.port_mapping)),
            access=sorted({r.access for r in crossing if r.access != UNCLASSIFIED}, key=CLASSES.index),
            remote_access=any(by_ip.get(r.src, {}).get('remote_access') for r in crossing),
            first_seen=min(times_first) if times_first else None,
            last_seen=max(times_last) if times_last else None,
            evidence='\n'.join(lines),
        ))

    asset_levels = {a['ip']: _level(a['purdue_level']) for a in assets if a.get('purdue_level') not in (None, '')}
    services = _plan_services(assets, requests, seen_in)
    return ImportPlan(zones=zones, flows=plans, asset_levels=asset_levels, services=services,
                      unidentified_ports=_unidentified_ports(assets, services),
                      hosts=_plan_hosts(assets, requests, {a['ip']: zone_of(a['ip']) for a in assets}))


def _plan_hosts(assets, requests, zone_of_ip):
    hosts = {}
    labels = dict(_flat_choices())

    def host(ip):
        return hosts.setdefault(ip, HostPlan(ip=ip, zone=zone_of_ip.get(ip, '')))

    def with_port(label, port_mapping):
        return f'{label} {port_mapping}'.strip() if port_mapping and port_mapping != label else label

    for r in requests:
        label = labels.get(r.protocol) or r.proto
        for ip in (r.src, r.dst, r.broker):
            if not ip:
                continue
            h = host(ip)
            for t in (r.first_seen, r.last_seen):
                if t:
                    h.first_seen = min(h.first_seen, t) if h.first_seen else t
                    h.last_seen = max(h.last_seen, t) if h.last_seen else t
        if r.broker:
            # Both ends talk to the broker, not to each other
            for ip in (r.src, r.dst):
                host(ip).peers.add(r.broker)
                host(r.broker).peers.add(ip)
                host(ip).uses.add(label)
            host(r.broker).serves.add(with_port(label, r.port_mapping))
            continue
        host(r.src).peers.add(r.dst)
        host(r.dst).peers.add(r.src)
        if r.connection == ConnectionChoices.REVERSE_CONNECT:
            # The source listens on the port and the destination connects to it, then answers its requests
            host(r.dst).serves.add(label)
            host(r.src).serves.add(with_port(label, r.port_mapping))
        else:
            host(r.dst).serves.add(with_port(label, r.port_mapping))
        host(r.src).uses.add(label)
    for a in assets:
        host(a['ip']).open_ports.update(a.get('open_ports') or [])
    return hosts


def unknown_assets(plan, site, vrf=None):
    """
    The observed hosts that match no device or VM at `site` in `vrf`, as report rows: the point of passive
    discovery. Hosts in a zone (inside the observed address space) come first.
    """
    from dcim.models import Device
    from virtualization.models import VirtualMachine

    known = set()
    for model in (Device, VirtualMachine):
        for address in model.objects.filter(site=site, primary_ip4__vrf=vrf).values_list(
                'primary_ip4__address', flat=True):
            known.add(str(address.ip))
    rows = []
    for ip, h in plan.hosts.items():
        if ip in known:
            continue
        address = ipaddress.ip_address(ip)
        rows.append({
            'ip': ip,
            'zone': h.zone,
            'private': 'yes' if address.is_private else 'no',
            'first_seen': h.first_seen.isoformat() if h.first_seen else '',
            'last_seen': h.last_seen.isoformat() if h.last_seen else '',
            'peers': len(h.peers),
            'serves': ', '.join(sorted(h.serves)),
            'uses': ', '.join(sorted(h.uses)),
            'open_ports': ', '.join(str(p) for p in sorted(h.open_ports)),
        })
    return sorted(rows, key=lambda r: (not r['zone'], r['private'] == 'no', ipaddress.ip_address(r['ip'])))


UNKNOWN_COLUMNS = ('ip', 'zone', 'private', 'first_seen', 'last_seen', 'peers', 'serves', 'uses', 'open_ports')


# The files of --unknown-import, in the order NetBox imports them, with their columns
UNKNOWN_IMPORT_FILES = (
    ('1-devices.csv', ('name', 'role', 'manufacturer', 'device_type', 'site', 'status', 'description')),
    ('2-interfaces.csv', ('device', 'name', 'type')),
    ('3-ip-addresses.csv', ('address', 'vrf', 'status', 'device', 'interface', 'is_primary')),
)
UNKNOWN_IMPORT_INTERFACE = 'eth0'


def unknown_import_rows(plan, site, vrf=None):
    """
    The unknown hosts that sit in a zone of the plant, as rows for NetBox's own bulk import of devices,
    interfaces and IP addresses: {file name: rows}. The importer does not create devices: a capture shows an
    address and what it talks, not what the machine is, so role, manufacturer and device type are left empty
    for a person to fill in. Hosts outside every zone, in an external zone or with a public address are left
    out. The mask comes from the most specific prefix NetBox has for the address in the VRF, else it is /32.
    """
    from ipam.models import Prefix

    from netbox_ot.models import Zone

    zone_types = {z.name: z.zone_type for z in plan.zones.values()}
    zone_types.update(Zone.objects.filter(site=site).values_list('name', 'zone_type'))
    devices, interfaces, addresses = [], [], []
    for row in unknown_assets(plan, site, vrf):
        if not row['zone'] or row['private'] != 'yes' or zone_types.get(row['zone']) == ZoneTypeChoices.EXTERNAL:
            continue
        ip = row['ip']
        name = f'unknown-{ip}'
        seen = [f"In zone {row['zone']}"]
        if row['first_seen']:
            seen.append(f"seen {row['first_seen'][:10]}..{row['last_seen'][:10]}")
        if row['serves']:
            seen.append(f"serves {row['serves']}")
        prefix = Prefix.objects.filter(vrf=vrf, prefix__net_contains_or_equals=ip).order_by(
            '-prefix__net_mask_length').first()
        devices.append({
            'name': name, 'role': '', 'manufacturer': '', 'device_type': '', 'site': site.name, 'status': 'active',
            'description': ('Found by passive discovery. ' + ', '.join(seen))[:200],
        })
        interfaces.append({'device': name, 'name': UNKNOWN_IMPORT_INTERFACE, 'type': 'other'})
        addresses.append({
            'address': f'{ip}/{prefix.prefix.prefixlen if prefix else 32}', 'vrf': vrf.name if vrf else '',
            'status': 'active', 'device': name, 'interface': UNKNOWN_IMPORT_INTERFACE, 'is_primary': 'true',
        })
    return dict(zip((name for name, _ in UNKNOWN_IMPORT_FILES), (devices, interfaces, addresses)))


def _flow_name(src, dst, protocol, connection=ConnectionChoices.CLIENT_SERVER, broker_zone=''):
    label = dict(_flat_choices()).get(protocol) if protocol else None
    name = f"{src} -> {dst} {label or '(unidentified)'}"
    if connection == ConnectionChoices.BROKERED:
        name += f' via broker in {broker_zone}'
    elif connection == ConnectionChoices.REVERSE_CONNECT:
        name += ' (reverse connect)'
    return name[:100]


def _flat_choices():
    for item in FlowProtocolChoices.CHOICES:
        if isinstance(item[1], (list, tuple)):
            yield from ((value, str(label)) for value, label in item[1])
        else:
            yield item[0], str(item[1])


def _plan_services(assets, requests, seen_in):
    services = {}

    def add(ip, protocol, role, line, port_mapping=''):
        sp = services.setdefault((ip, protocol, role), ServicePlan(ip=ip, protocol=protocol, role=role))
        if port_mapping and port_mapping not in sp.port_mappings:
            sp.port_mappings.append(port_mapping)
        if line not in sp.evidence:
            sp.evidence.append(line)

    known = {a['ip'] for a in assets}
    industrial = set(IndustrialProtocolChoices.values())
    for r in requests:
        if r.protocol not in industrial:
            continue
        what = f'{r.proto} {r.func} x{r.count}'.replace('  ', ' ').strip()
        if r.connection == ConnectionChoices.BROKERED:
            topic = f' on {r.topic}' if r.topic else ''
            if r.broker in known:
                add(r.broker, r.protocol, 'server', f'Broker for {r.src} -> {r.dst}{topic} ({seen_in})',
                    r.port_mapping)
            if r.src in known:
                add(r.src, r.protocol, 'publisher', f'Published{topic} through {r.broker} to {r.dst} ({seen_in})')
            if r.dst in known:
                add(r.dst, r.protocol, 'subscriber', f'Received{topic} through {r.broker} from {r.src} ({seen_in})')
            continue
        reverse = r.connection == ConnectionChoices.REVERSE_CONNECT
        if r.dst in known:
            # In a reverse connect the port is the client's (it listens), not the server's
            add(r.dst, r.protocol, 'server', f'Answered {what} from {r.src} ({seen_in})',
                '' if reverse else r.port_mapping)
        if r.src in known:
            how = ' over a connection it opened (reverse connect)' if reverse else ''
            add(r.src, r.protocol, 'client', f'Sent {what} to {r.dst}{how} ({seen_in})')
    for a in assets:
        for s in a.get('services') or []:
            protocol = protocol_value(s['proto'])
            if protocol not in industrial:
                continue
            on_port = f" on port {s['port']}" if s.get('port') else ''
            add(a['ip'], protocol, 'server', f"Identified as {s['proto']}{on_port} ({seen_in})",
                _port_mapping(s.get('port'), s.get('transport'), protocol))
    return sorted(services.values(), key=lambda s: (ipaddress.ip_address(s.ip), s.protocol, s.role))


def _unidentified_ports(assets, services):
    explained = defaultdict(set)  # ip -> ports an identified server service accounts for
    for sp in services:
        if sp.role in LISTENING:
            ports = [int(m.split('/')[1]) for m in sp.port_mappings] or \
                IndustrialProtocolChoices.DEFAULT_PORTS.get(sp.protocol, [])
            explained[sp.ip].update(ports)
    return [
        OpenPort(ip=a['ip'], port=port, candidates=OT_PORTS[port])
        for a in assets for port in sorted(set(a.get('open_ports') or []))
        if port in OT_PORTS and port not in explained[a['ip']]
    ]


class _Resolver:
    """Finds devices, VMs and prefixes for an address within one site and one VRF (None: the global table)."""

    def __init__(self, site, vrf, log, stats):
        self.site, self.vrf, self.log, self.stats = site, vrf, log, stats
        self.where = f"site {site}" + (f", VRF {vrf}" if vrf else ', global table')
        self._assets, self._prefixes = {}, {}

    def asset(self, ip):
        """The one device or VM with this primary IPv4 in the site and VRF, else None (logged once)."""
        if ip in self._assets:
            return self._assets[ip]
        from dcim.models import Device
        from virtualization.models import VirtualMachine

        lookup = {'site': self.site, 'primary_ip4__address__net_host': ip, 'primary_ip4__vrf': self.vrf}
        found = list(Device.objects.filter(**lookup)[:2]) + list(VirtualMachine.objects.filter(**lookup)[:2])
        asset = found[0] if len(found) == 1 else None
        if not found:
            self.stats['assets not found in NetBox'] += 1
            self.log(f'{ip}: no device or VM with this primary IPv4 ({self.where})')
        elif len(found) > 1:
            self.stats['assets matched more than once (skipped)'] += 1
            self.log(f"{ip}: several devices/VMs have this primary IPv4 ({self.where}): "
                     f"{', '.join(str(a) for a in found)}; skipped")
        self._assets[ip] = asset
        return asset

    def prefix(self, ip):
        """
        The most specific active (non-container) prefix that holds `ip` in this VRF and is scoped to the site, its
        location, region or site group, or unscoped. A narrower scope wins at equal length; a tie is ambiguous.
        """
        if ip in self._prefixes:
            return self._prefixes[ip]
        from django.contrib.contenttypes.models import ContentType
        from django.db.models import Q

        from dcim.models import Region, SiteGroup
        from ipam.choices import PrefixStatusChoices
        from ipam.models import Prefix

        # The cached _region/_site_group are also set on site-scoped prefixes, so check the scope type too
        site = self.site
        scope = Q(scope_type__isnull=True) | Q(_site=site)
        if site.region_id:
            scope |= Q(scope_type=ContentType.objects.get_for_model(Region),
                       _region__in=site.region.get_ancestors(include_self=True))
        if site.group_id:
            scope |= Q(scope_type=ContentType.objects.get_for_model(SiteGroup),
                       _site_group__in=site.group.get_ancestors(include_self=True))
        candidates = (Prefix.objects.filter(scope, vrf=self.vrf, prefix__net_contains_or_equals=ip)
                      .exclude(status=PrefixStatusChoices.STATUS_CONTAINER))

        def rank(p):
            narrowness = 3 if p._location_id else 2 if p._site_id else 1 if p.scope_type_id else 0
            return p.prefix.prefixlen, narrowness

        ranked = sorted(candidates, key=rank, reverse=True)
        prefix = ranked[0] if ranked else None
        if not ranked:
            self.stats['addresses without a prefix in NetBox'] += 1
            self.log(f'{ip}: no prefix in NetBox holds this address ({self.where})')
        elif len(ranked) > 1 and rank(ranked[0]) == rank(ranked[1]):
            prefix = None
            self.stats['addresses in duplicate prefixes (skipped)'] += 1
            self.log(f'{ip}: duplicate prefixes {ranked[0]} hold this address ({self.where}); not linked')
        self._prefixes[ip] = prefix
        return prefix


def _widest(pick, *times):
    times = [t for t in times if t]
    return pick(times) if times else None


def _merge(existing, new, order=None):
    merged = list(existing) + [x for x in new if x not in existing]
    return sorted(merged, key=order.index) if order else merged


def apply_plan(plan, site, vrf=None, log=print):
    """
    Create/update zones, flows, services and Purdue levels for `site`, matching devices, VMs and prefixes
    within `site` and `vrf` (None: the global table). Call inside a transaction.
    """
    from extras.models import CustomField

    from ..customfields import PURDUE_CF_NAME
    from ..models import Conduit, Flow, IndustrialService, Zone

    stats = defaultdict(int)
    resolver = _Resolver(site, vrf, log, stats)
    has_cf = CustomField.objects.filter(name=PURDUE_CF_NAME).exists()

    # A prefix is linked to a zone only if it holds no assets of another zone
    zones_of_prefix = defaultdict(set)
    for zp in plan.zones.values():
        for ip in zp.member_ips:
            prefix = resolver.prefix(ip)
            if prefix:
                zones_of_prefix[prefix].add(zp.name)
    for prefix, names in zones_of_prefix.items():
        if len(names) > 1:
            stats['prefixes holding several zones (not linked)'] += 1
            log(f"prefix {prefix} holds assets of zones {', '.join(sorted(names))}; not linked")

    zone_objs = {}
    for zp in plan.zones.values():
        zone = Zone.objects.filter(site=site, name=zp.name).first()
        if zone is None:
            zone = Zone(site=site, name=zp.name, slug=zp.slug, zone_type=zp.zone_type, purdue_level=zp.purdue_level,
                        description=zp.description[:200])
            zone.full_clean()
            zone.save()
            stats['zones created'] += 1
            log(f'zone created: {zone} ({zone.get_zone_type_display()})')
        else:
            zone.snapshot()
            if not zone.purdue_level and zp.purdue_level:
                zone.purdue_level = zp.purdue_level
                zone.save()
                stats['zones updated'] += 1
        zone_objs[zp.name] = zone

        prefixes = {resolver.prefix(ip) for ip in zp.member_ips} - {None}
        for prefix in sorted(prefixes, key=lambda p: p.prefix):
            if zones_of_prefix[prefix] == {zp.name} and not zone.prefixes.filter(pk=prefix.pk).exists():
                zone.prefixes.add(prefix)
                stats['prefixes linked'] += 1

        for ip in zp.member_ips:
            asset = resolver.asset(ip)
            if asset is None:
                continue
            members = zone.devices if asset._meta.model_name == 'device' else zone.virtual_machines
            if not members.filter(pk=asset.pk).exists():
                members.add(asset)
                stats['members added'] += 1
            level = plan.asset_levels.get(ip)
            if has_cf and level and not asset.custom_field_data.get(PURDUE_CF_NAME):
                asset.snapshot()
                asset.custom_field_data[PURDUE_CF_NAME] = level
                asset.save()
                stats['asset levels set'] += 1

    for fp in plan.flows:
        src, dst = zone_objs[fp.source], zone_objs[fp.destination]
        broker = zone_objs[fp.broker_zone] if fp.broker_zone else None
        flow = Flow.objects.filter(source_zone=src, destination_zone=dst, protocol=fp.protocol,
                                   connection=fp.connection, broker_zone=broker).order_by('pk').first()
        created = flow is None
        if created:
            name, n = fp.name, 2
            while Flow.objects.filter(source_zone=src, destination_zone=dst, name=name).exists():
                name, n = f'{fp.name[:94]} ({n})', n + 1
            flow = Flow(source_zone=src, destination_zone=dst, protocol=fp.protocol, name=name,
                        connection=fp.connection, broker_zone=broker)
        else:
            flow.snapshot()
        # Observations are merged; the verdict, its decider and dates, the conduit and the hops are a person's.
        new = {
            'port_mappings': _merge(flow.port_mappings, fp.port_mappings),
            'access': _merge(flow.access, fp.access, order=list(CLASSES)),
            'topics': _merge(flow.topics, fp.topics),
            # A flow out of an external (supplier, MSP, outside) zone is remote access by definition
            'remote_access': flow.remote_access or fp.remote_access or src.zone_type == ZoneTypeChoices.EXTERNAL,
            'first_seen': _widest(min, flow.first_seen, fp.first_seen),
            'last_seen': _widest(max, flow.last_seen, fp.last_seen),
            'evidence': fp.evidence,
        }
        if flow.conduit_id is None:
            candidates = Conduit.objects.filter(zones=src).filter(zones=dst)
            if broker is not None:
                candidates = candidates.filter(zones=broker)
            candidates = list(candidates[:2])
            if len(candidates) == 1:
                new['conduit'] = candidates[0]
        if not created and all(getattr(flow, k) == v for k, v in new.items()):
            stats['flows unchanged'] += 1
            continue
        for k, v in new.items():
            setattr(flow, k, v)
        flow.full_clean()
        flow.save()
        stats['flows created' if created else 'flows updated'] += 1
        log(f"flow {'created' if created else 'updated'}: {flow}")

    for sp in plan.services:
        asset = resolver.asset(sp.ip)
        if asset is None:
            continue
        is_device = asset._meta.model_name == 'device'
        lookup = {'device': asset} if is_device else {'virtual_machine': asset}
        service = IndustrialService.objects.filter(protocol=sp.protocol, role=sp.role, **lookup).first()
        evidence = '\n'.join(sp.evidence)
        created = service is None
        if created:
            service = IndustrialService(protocol=sp.protocol, role=sp.role, evidence=evidence, **lookup)
        else:
            service.snapshot()
        changed = created or service.evidence != evidence
        service.evidence = evidence
        if service.service_id is None and sp.role in LISTENING and sp.port_mappings:
            service.service = _application_service(asset, sp, stats, log)
            changed = True
        if not changed:
            stats['services unchanged'] += 1
            continue
        service.full_clean()
        service.save()
        stats['services created' if created else 'services updated'] += 1
    return dict(stats)


def _application_service(asset, sp, stats, log):
    """The asset's NetBox application service with one of these ports, created with them if there is none."""
    from ipam.models import Service

    existing = Service.objects.filter(
        parent_object_type__app_label=asset._meta.app_label, parent_object_type__model=asset._meta.model_name,
        parent_object_id=asset.pk, port_mappings__overlap=sp.port_mappings,
    ).first()
    if existing:
        return existing
    label = dict(_flat_choices()).get(sp.protocol, sp.protocol)
    service = Service(parent=asset, name=label[:100], port_mappings=list(sp.port_mappings),
                      description='Seen by netbox-ot import')
    service.full_clean()
    service.save()
    if asset.primary_ip4:
        service.ipaddresses.add(asset.primary_ip4)
    stats['application services created'] += 1
    log(f"application service created: {asset} {label} {', '.join(sp.port_mappings)}")
    return service
