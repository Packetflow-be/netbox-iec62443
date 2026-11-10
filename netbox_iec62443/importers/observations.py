"""
Importer for observation files: what was seen on an OT network, in the plugin's documented import format
(docs/import-format.md): assets.json, flows.json and optionally summary.json. Any tool can write them:
a script over Zeek/ICSNPP or Malcolm logs, an asset-discovery export, or a spreadsheet.

One import covers one site and one routing domain (the global table or one VRF). Duplicate machine
networks are normal in OT, so every lookup in NetBox is scoped to that site and VRF.

  zones     one per zone name in assets.json. A zone that mixes controllers (Purdue 0-1) with supervisory
            assets (2) or site operations (3+) can be split into one zone per band, e.g. "Cell A (control)"
            and "Cell A (supervisory)", so the paths between them become conduits. Splitting is opt-in: per
            zone (`split_zones`) or every mixed zone (True). Purdue level = the lowest level among the zone's
            assets. Addresses not in assets.json fall into one zone without a Purdue level (`outside_zone`).
  prefixes  the most specific prefix NetBox already has for each asset's address, in the site and VRF.
            The importer never creates prefixes, and does not link a prefix that holds assets of two zones.
  conduits  one per directed zone pair, from summary.json "zone_pairs" and from OT requests between zones;
            protocols = OT protocols/functions crossing it; via = the assets that sent requests changing the
            target (write, control, program; see functions.py) or are marked as remote access; remote_access =
            an asset marked `remote_access` in assets.json sent OT requests across it; evidence = counts and
            the OT request lines with their class.
  devices   matched by primary IPv4 within the site and VRF; an address that matches more than one device or
            VM is skipped and reported. Matched assets get the zone membership and their Purdue level.
  services  industrial services per asset: a server for every protocol it answered or that assets.json names
            in its "services", a client for every protocol it sent requests in. An open port alone does not
            say which protocol listens there (port 102 is S7comm or IEC 61850 MMS), so it creates no service;
            open OT ports that no identified service explains are listed in the plan for a person to resolve.

Re-running is safe: it adds members and refreshes evidence, but never overwrites a human decision
(a conduit's "allowed", a zone's or device's Purdue level once set).
"""
import ipaddress
from collections import defaultdict
from dataclasses import dataclass, field

from django.utils.text import slugify

from ..choices import IndustrialProtocolChoices
from .functions import CLASSES, MODIFYING, classify

# Protocol names in the analysis output (Zeek/ICSNPP, tshark) -> IndustrialProtocolChoices values
PROTOCOL_NAMES = {
    's7comm': 's7comm', 's7comm-plus': 's7comm-plus', 's7comm_plus': 's7comm-plus', 'modbus': 'modbus-tcp',
    'modbus/tcp': 'modbus-tcp', 'enip': 'ethernet-ip', 'ethernet/ip': 'ethernet-ip', 'cip': 'ethernet-ip',
    'dnp3': 'dnp3', 'bacnet': 'bacnet-ip', 'bacnet/ip': 'bacnet-ip', 'opcua': 'opc-ua', 'opc ua': 'opc-ua',
    'opcua-binary': 'opc-ua', 'opcua_binary': 'opc-ua', 'iec104': 'iec-104', 'iec-104': 'iec-104',
    'iec 60870-5-104': 'iec-104', 'mms': 'iec-61850-mms', 'iec61850': 'iec-61850-mms', 'goose': 'iec-61850-goose',
    'profinet': 'profinet', 'profinet_io_cm': 'profinet', 'mqtt': 'mqtt', 'hart-ip': 'hart-ip', 'hart_ip': 'hart-ip',
    'omron fins': 'omron-fins', 'fins': 'omron-fins',
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


@dataclass
class ZonePlan:
    name: str
    slug: str
    purdue_level: str = ''
    description: str = ''
    member_ips: list = field(default_factory=list)


@dataclass
class ConduitPlan:
    name: str
    source: str
    destination: str
    protocols: str = ''
    via: str = ''
    remote_access: bool = False
    evidence: str = ''


@dataclass
class ServicePlan:
    ip: str
    protocol: str
    role: str
    ports: list = field(default_factory=list)
    evidence: list = field(default_factory=list)


@dataclass
class OpenPort:
    """An open OT port that no identified service on the asset explains."""
    ip: str
    port: int
    candidates: list  # protocol values that commonly use this port


@dataclass
class ImportPlan:
    zones: dict
    conduits: list
    asset_levels: dict  # ip -> Purdue level string
    services: list = field(default_factory=list)
    unidentified_ports: list = field(default_factory=list)


@dataclass
class _Request:
    src: str
    dst: str
    proto: str  # as written in the input
    protocol: str | None  # plugin protocol value, None if not recognised
    func: str
    count: int
    access: str  # functions.READ ... UNCLASSIFIED

    @property
    def line(self):
        return f'{self.src} -> {self.dst} {self.proto} {self.func} x{self.count} [{self.access}]'.replace('  ', ' ')


def protocol_value(name):
    """Plugin protocol value for a protocol name from the input, or None."""
    name = str(name)
    if name in IndustrialProtocolChoices.values():
        return name
    return PROTOCOL_NAMES.get(name.lower())


def validate(assets, flows, summary):
    """Raise ValueError with the offending entry if the input does not follow docs/import-format.md."""
    def ip(value, where):
        try:
            ipaddress.IPv4Address(value)
        except (ipaddress.AddressValueError, ValueError, TypeError):
            raise ValueError(f'{where}: {value!r} is not an IPv4 address')

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
            if 'port' in s and not (isinstance(s['port'], int) and 1 <= s['port'] <= 65535):
                raise ValueError(f'{where}.services[{j}]: port {s["port"]!r} is not a TCP/UDP port')
    for i, f in enumerate(flows):
        where = f'flows.json[{i}]'
        if not isinstance(f, dict) or not all(f.get(k) for k in ('src', 'dst', 'proto')):
            raise ValueError(f'{where}: "src", "dst" and "proto" are required')
        ip(f['src'], where)
        ip(f['dst'], where)
        if f.get('access') not in (None, '') and str(f['access']).lower() not in CLASSES:
            raise ValueError(f'{where}: access {f["access"]!r} is not one of {", ".join(CLASSES)}')


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


def build_plan(assets, flows, summary, outside_zone='Outside', split_zones=None):
    """
    Turn observation files into zones, conduits, services and per-asset Purdue levels. No database access.

    outside_zone  name of the zone for addresses that are not in assets.json
    split_zones   zone names to split per Purdue band, or True for every mixed zone
    """
    validate(assets, flows, summary)
    by_ip = {a['ip']: a for a in assets}
    base_of_ip = {a['ip']: a['zone'] for a in assets}

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
    for z in zones.values():
        levels = [float(by_ip[ip]['purdue_level']) for ip in z.member_ips
                  if by_ip[ip].get('purdue_level') not in (None, '')]
        z.purdue_level = _level(min(levels)) if levels else ''
    # The most critical part of each split zone gets traffic that can't be pinned to one part
    critical = {}
    for name, z in zones.items():
        base = base_of_zone[name]
        if base in split and z.purdue_level and (
                base not in critical or float(z.purdue_level) < float(zones[critical[base]].purdue_level)):
            critical[base] = name

    def ensure_outside():
        if outside_zone not in zones:
            zones[outside_zone] = ZonePlan(name=outside_zone, slug=slugify(outside_zone),
                                           description='Addresses not listed in the observations')
            base_of_zone[outside_zone] = outside_zone

    captures = ', '.join(summary.get('captures', []))
    hours = summary.get('hours')
    seen_in = (f"captures {captures}" if captures else 'the observations') + (f" ({hours} h)" if hours else '')

    requests = []
    for f in flows:
        protocol = protocol_value(f['proto'])
        access = str(f.get('access') or '').lower() or classify(protocol, f.get('func'))
        requests.append(_Request(src=f['src'], dst=f['dst'], proto=str(f['proto']), protocol=protocol,
                                 func=str(f.get('func') or ''), count=f.get('count', 1), access=access))

    # OT requests between zones, keyed by (source zone, destination zone)
    ot = defaultdict(list)
    for r in requests:
        zs, zd = zone_of(r.src), zone_of(r.dst)
        if zs != zd:
            ot[(zs, zd)].append(r)

    # Directed zone pairs: from zone_pairs (with connection counts), then OT-only pairs
    pairs = {}  # (src, dst) -> evidence header line
    for pair in summary.get('zone_pairs', []):
        src, dst, count = base_name(pair['from']), base_name(pair['to']), pair['count']
        if src == dst:
            continue
        line = f"Passively seen: {count} connection(s) from {src} to {dst} in {seen_in}."
        if src in split or dst in split:
            keys = [k for k in ot if (base_of_zone.get(k[0], outside_zone), base_of_zone.get(k[1], outside_zone))
                    == (src, dst)]
            if not keys:
                keys = [(critical.get(src, src), critical.get(dst, dst))]
        else:
            keys = [(src, dst)]
        for key in keys:
            pairs.setdefault(key, line)
    for key in ot:
        pairs.setdefault(key, f"Passively seen: OT requests from {key[0]} to {key[1]} in {seen_in}.")

    conduits = []
    for (src, dst), header in pairs.items():
        for name in (src, dst):
            if name == outside_zone:
                ensure_outside()
        crossing = ot.get((src, dst), [])
        protocols = defaultdict(list)
        for r in crossing:
            funcs = protocols[r.proto]
            if r.func and r.func not in funcs:
                funcs.append(r.func)
        remote = [r.src for r in crossing if by_ip.get(r.src, {}).get('remote_access')]
        modifying = [r.src for r in crossing if r.access in MODIFYING]
        via_ips = list(dict.fromkeys(remote + modifying))
        via = '; '.join(f"{by_ip.get(ip, {}).get('role') or 'unknown'} ({ip})" for ip in via_ips)
        lines = [header] + [f'OT: {r.line}' for r in sorted(crossing, key=lambda r: -r.count)]
        conduits.append(ConduitPlan(
            name=f'{src} -> {dst}', source=src, destination=dst,
            protocols='; '.join(f"{p} ({', '.join(funcs)})" if funcs else p for p, funcs in protocols.items()),
            via=via, remote_access=bool(remote), evidence='\n'.join(lines),
        ))

    asset_levels = {a['ip']: _level(a['purdue_level']) for a in assets if a.get('purdue_level') not in (None, '')}
    services = _plan_services(assets, requests, seen_in)
    return ImportPlan(zones=zones, conduits=conduits, asset_levels=asset_levels, services=services,
                      unidentified_ports=_unidentified_ports(assets, services))


def _plan_services(assets, requests, seen_in):
    services = {}

    def add(ip, protocol, role, line, port=None):
        sp = services.setdefault((ip, protocol, role), ServicePlan(ip=ip, protocol=protocol, role=role))
        if port and port not in sp.ports:
            sp.ports.append(port)
        if line not in sp.evidence:
            sp.evidence.append(line)

    known = {a['ip'] for a in assets}
    for r in requests:
        if not r.protocol:
            continue
        what = f'{r.proto} {r.func} x{r.count}'.replace('  ', ' ').strip()
        if r.dst in known:
            add(r.dst, r.protocol, 'server', f'Answered {what} from {r.src} ({seen_in})')
        if r.src in known:
            add(r.src, r.protocol, 'client', f'Sent {what} to {r.dst} ({seen_in})')
    for a in assets:
        for s in a.get('services') or []:
            protocol = protocol_value(s['proto'])
            on_port = f" on port {s['port']}" if s.get('port') else ''
            add(a['ip'], protocol, 'server', f"Identified as {s['proto']}{on_port} ({seen_in})", port=s.get('port'))
    return sorted(services.values(), key=lambda s: (ipaddress.ip_address(s.ip), s.protocol, s.role))


def _unidentified_ports(assets, services):
    explained = defaultdict(set)  # ip -> ports an identified server service accounts for
    for sp in services:
        if sp.role == 'server':
            explained[sp.ip].update(sp.ports or IndustrialProtocolChoices.DEFAULT_PORTS.get(sp.protocol, []))
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


def apply_plan(plan, site, vrf=None, log=print):
    """
    Create/update zones, conduits, services and Purdue levels for `site`, matching devices, VMs and prefixes
    within `site` and `vrf` (None: the global table). Call inside a transaction.
    """
    from extras.models import CustomField

    from ..customfields import PURDUE_CF_NAME
    from ..models import Conduit, IndustrialService, Zone

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
            zone = Zone(site=site, name=zp.name, slug=zp.slug, purdue_level=zp.purdue_level,
                        description=zp.description[:200])
            zone.full_clean()
            zone.save()
            stats['zones created'] += 1
            log(f'zone created: {zone}')
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

    for cp in plan.conduits:
        src, dst = zone_objs[cp.source], zone_objs[cp.destination]
        conduit = Conduit.objects.filter(source_zone=src, destination_zone=dst, name=cp.name).first()
        created = conduit is None
        if created:
            conduit = Conduit(source_zone=src, destination_zone=dst, name=cp.name)
        else:
            conduit.snapshot()
        # Evidence fields are refreshed; `allowed` is a human decision and is never touched here.
        new = {
            'protocols': cp.protocols[:200],
            'via': cp.via[:200] or conduit.via,
            'remote_access': conduit.remote_access or cp.remote_access,
            'evidence': cp.evidence,
        }
        if not created and all(getattr(conduit, k) == v for k, v in new.items()):
            stats['conduits unchanged'] += 1
            continue
        for k, v in new.items():
            setattr(conduit, k, v)
        conduit.full_clean()
        conduit.save()
        stats['conduits created' if created else 'conduits updated'] += 1
        log(f"conduit {'created' if created else 'updated'}: {cp.name}")

    for sp in plan.services:
        asset = resolver.asset(sp.ip)
        if asset is None:
            continue
        is_device = asset._meta.model_name == 'device'
        lookup = {'device': asset} if is_device else {'virtual_machine': asset}
        service = IndustrialService.objects.filter(protocol=sp.protocol, role=sp.role, **lookup).first()
        evidence = '\n'.join(sp.evidence)
        if service is None:
            service = IndustrialService(protocol=sp.protocol, role=sp.role, ports=list(sp.ports), evidence=evidence,
                                        **lookup)
            if is_device and asset.primary_ip4 and asset.primary_ip4.assigned_object_type.model == 'interface':
                service.interface_id = asset.primary_ip4.assigned_object_id
            service.full_clean()
            service.save()
            stats['services created'] += 1
        elif service.evidence != evidence:
            service.snapshot()
            service.evidence = evidence
            service.full_clean()
            service.save()
            stats['services updated'] += 1
        else:
            stats['services unchanged'] += 1
    return dict(stats)
