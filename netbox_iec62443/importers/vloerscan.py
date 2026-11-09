"""
Importer for the Vloerscan prototype's analysis output (assets.json, flows.json, summary.json).

It mirrors the prototype's zone logic (analyze.py): each asset carries its zone, assigned per /24
segment; cross-zone traffic is summarised in summary.json "zone_pairs"; OT requests (S7comm, Modbus)
are listed in flows.json. From that:

  zones     one per zone name (optionally renamed). A zone that mixes controllers (Purdue 0-1) with
            supervisory assets (2) or site operations (3+) can be split into one zone per band, e.g.
            "Z1 Cell A (control)" and "Z1 Cell A (supervisory)", so the paths between them become
            conduits. Purdue level = the lowest level among the zone's assets; prefixes = the /24
            segments of its assets. Zones in zone_pairs without assets (outside the scanned floor)
            become one zone without a Purdue level, named by `outside_zone`. Splitting is opt-in:
            per zone (`split_zones`) or for every mixed zone (`split_zones=True`).
  conduits  one per directed zone pair, from zone_pairs and from OT requests between zones;
            protocols = OT protocols/functions crossing it; via = assets that wrote into another zone;
            remote_access = such a writer is a router (a supplier's 4G/VPN router); evidence = counts
            and OT flow lines.
  devices   matched by primary IPv4 address; get the zone membership and their Purdue level.

Re-running is safe: it adds members and refreshes evidence, but never overwrites a human decision
(a conduit's "allowed", a zone's or device's Purdue level once set).
"""
import ipaddress
from collections import defaultdict
from dataclasses import dataclass, field

from django.utils.text import slugify

WRITE_FUNCS = ('Write',)
BANDS = ('control', 'supervisory', 'operations')


@dataclass
class ZonePlan:
    name: str
    slug: str
    purdue_level: str = ''
    description: str = ''
    prefixes: list = field(default_factory=list)
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
class ImportPlan:
    zones: dict
    conduits: list
    asset_levels: dict  # ip -> Purdue level string


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


def build_plan(assets, flows, summary, renames=None, outside_zone='Outside', split_zones=None):
    """
    Turn the prototype's JSON into zones, conduits and per-asset Purdue levels. No database access.

    renames       {input zone name: new name}, e.g. to translate the prototype's zone names
    outside_zone  name of the zone for everything outside the scanned floor
    split_zones   zone names (input or renamed) to split per Purdue band, or True for every mixed zone
    """
    renames = renames or {}
    by_ip = {a['ip']: a for a in assets}
    base_of_ip = {a['ip']: renames.get(a['zone'], a['zone']) for a in assets}

    bands = defaultdict(set)
    for a in assets:
        bands[base_of_ip[a['ip']]].add(_band(a['purdue_level']))
    if split_zones is True:
        wanted = set(bands)
    else:
        wanted = {renames.get(z, z) for z in (split_zones or ())}
    split = {z for z, b in bands.items() if z in wanted and len(b - {None}) > 1}

    def zone_of(ip):
        if ip not in by_ip:
            return outside_zone
        base, band = base_of_ip[ip], _band(by_ip[ip]['purdue_level'])
        return f'{base} ({band})' if base in split and band else base

    def base_name(name):
        name = renames.get(name, name)
        return name if name in bands else outside_zone

    zones, base_of_zone = {}, {}
    for a in assets:
        name = zone_of(a['ip'])
        z = zones.setdefault(name, ZonePlan(name=name, slug=slugify(name)))
        base_of_zone[name] = base_of_ip[a['ip']]
        z.member_ips.append(a['ip'])
        net = str(ipaddress.ip_network(f"{a['ip']}/24", strict=False))
        if net not in z.prefixes:
            z.prefixes.append(net)
    for z in zones.values():
        levels = [float(by_ip[ip]['purdue_level']) for ip in z.member_ips if by_ip[ip]['purdue_level'] is not None]
        z.purdue_level = _level(min(levels)) if levels else ''
        z.prefixes.sort(key=lambda n: ipaddress.ip_network(n))
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
                                           description='Outside the scanned floor')
            base_of_zone[outside_zone] = outside_zone

    captures = ', '.join(summary.get('captures', []))
    hours = summary.get('hours')
    seen_in = f"captures {captures}" + (f" ({hours} h)" if hours else '')

    # OT requests between zones, keyed by (source zone, destination zone)
    ot = defaultdict(list)
    for f in flows:
        zs, zd = zone_of(f['src']), zone_of(f['dst'])
        if zs != zd:
            ot[(zs, zd)].append(f)

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
        for f in crossing:
            if f['func'] and f['func'] not in protocols[f['proto']]:
                protocols[f['proto']].append(f['func'])
        writers = []
        for f in crossing:
            if any(w in (f['func'] or '') for w in WRITE_FUNCS) and f['src'] not in writers:
                writers.append(f['src'])
        via = '; '.join(f"{by_ip.get(ip, {}).get('role', 'unknown')} ({ip})" for ip in writers)
        remote = any('router' in by_ip.get(ip, {}).get('role', '').lower() for ip in writers)
        lines = [header] + [
            f"OT: {f['src']} -> {f['dst']} {f['proto']} {f['func']} x{f['count']}"
            for f in sorted(crossing, key=lambda f: -f['count'])
        ]
        conduits.append(ConduitPlan(
            name=f'{src} -> {dst}', source=src, destination=dst,
            protocols='; '.join(f"{p} ({', '.join(funcs)})" for p, funcs in protocols.items()),
            via=via, remote_access=remote, evidence='\n'.join(lines),
        ))

    asset_levels = {a['ip']: _level(a['purdue_level']) for a in assets if a['purdue_level'] is not None}
    return ImportPlan(zones=zones, conduits=conduits, asset_levels=asset_levels)


def apply_plan(plan, site, log=print):
    """Create/update zones, conduits and device levels for `site`. Call inside a transaction."""
    from dcim.models import Device
    from extras.models import CustomField
    from ipam.models import Prefix
    from virtualization.models import VirtualMachine

    from ..customfields import PURDUE_CF_NAME
    from ..models import Conduit, Zone

    stats = defaultdict(int)
    has_cf = CustomField.objects.filter(name=PURDUE_CF_NAME).exists()
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

        for net in zp.prefixes:
            prefix = Prefix.objects.filter(prefix=net).first()
            if prefix is None:
                prefix = Prefix(prefix=net, status='active', description=zp.name[:200])
                prefix.full_clean()
                prefix.save()
                stats['prefixes created'] += 1
            if not zone.prefixes.filter(pk=prefix.pk).exists():
                zone.prefixes.add(prefix)
                stats['prefixes linked'] += 1

        for ip in zp.member_ips:
            asset = (Device.objects.filter(primary_ip4__address__net_host=ip).first()
                     or VirtualMachine.objects.filter(primary_ip4__address__net_host=ip).first())
            if asset is None:
                stats['assets not found in NetBox'] += 1
                log(f'no device or VM with primary IP {ip}')
                continue
            members = zone.devices if isinstance(asset, Device) else zone.virtual_machines
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
    return dict(stats)
