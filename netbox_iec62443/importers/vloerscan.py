"""
Importer for the Vloerscan prototype's analysis output (assets.json, flows.json, summary.json).

It mirrors the prototype's zone logic (analyze.py): each asset already carries its zone ("Z1 Cel A", ...),
assigned per /24 segment; cross-zone traffic is summarised in summary.json "zone_pairs"; OT requests
(S7comm, Modbus) are listed in flows.json. From that:

  zones     one per zone name; Purdue level = the lowest (most critical) level among its assets;
            prefixes = the /24 segments of its assets. "Onbekend" (outside the scanned floor) becomes a
            zone without a Purdue level.
  conduits  one per directed zone pair seen in zone_pairs; protocols = OT protocols/functions crossing it;
            via = assets that wrote into another zone (as in finding 2 of the prototype); remote_access =
            such a writer is a router (a supplier 4G/VPN box); evidence = counts and OT flow lines.
  devices   matched by primary IPv4 address; get the zone membership and their Purdue level.

Re-running is safe: it adds members and refreshes evidence, but never overwrites a human decision
(a conduit's "allowed", a zone's or device's Purdue level once set).
"""
import ipaddress
from collections import defaultdict
from dataclasses import dataclass, field

from django.utils.text import slugify

OUTSIDE_ZONE = 'Onbekend'
WRITE_FUNCS = ('Write',)


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


def build_plan(assets, flows, summary):
    """Turn the prototype's JSON into zones, conduits and per-asset Purdue levels. No database access."""
    by_ip = {a['ip']: a for a in assets}
    zone_of_ip = {a['ip']: a['zone'] for a in assets}

    zones = {}
    for a in assets:
        z = zones.setdefault(a['zone'], ZonePlan(name=a['zone'], slug=slugify(a['zone'])))
        z.member_ips.append(a['ip'])
        net = str(ipaddress.ip_network(f"{a['ip']}/24", strict=False))
        if net not in z.prefixes:
            z.prefixes.append(net)
    for z in zones.values():
        levels = [float(by_ip[ip]['purdue_level']) for ip in z.member_ips if by_ip[ip]['purdue_level'] is not None]
        z.purdue_level = _level(min(levels)) if levels else ''
        z.prefixes.sort(key=lambda n: ipaddress.ip_network(n))

    captures = ', '.join(summary.get('captures', []))
    hours = summary.get('hours')
    seen_in = f"captures {captures}" + (f" ({hours} h)" if hours else '')

    # OT requests crossing zones, keyed by (source zone, destination zone)
    ot = defaultdict(list)
    for f in flows:
        zs, zd = zone_of_ip.get(f['src'], OUTSIDE_ZONE), zone_of_ip.get(f['dst'], OUTSIDE_ZONE)
        if zs != zd:
            ot[(zs, zd)].append(f)

    conduits = []
    for pair in summary.get('zone_pairs', []):
        src, dst, count = pair['from'], pair['to'], pair['count']
        if src == dst:
            continue
        for name in (src, dst):
            if name not in zones:
                zones[name] = ZonePlan(
                    name=name, slug=slugify(name),
                    description='Outside the scanned floor' if name == OUTSIDE_ZONE else '',
                )
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
        lines = [f"Passively seen: {count} connection(s) from {src} to {dst} in {seen_in}."]
        lines += [
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
