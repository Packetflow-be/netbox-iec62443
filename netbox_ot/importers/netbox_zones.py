"""The zone map of a site as NetBox knows it: zone prefixes and member addresses, within one VRF."""
from .zeek import ZoneMap


def _depth(zone):
    depth, seen = 0, set()
    while zone.parent_id and zone.parent_id not in seen:
        seen.add(zone.parent_id)
        depth, zone = depth + 1, zone.parent
    return depth


def zone_map_from_netbox(site, vrf=None):
    """
    ZoneMap of `site`: each zone's prefixes in `vrf` (None: the global table) and the primary IPv4 addresses of
    its member devices and VMs. A sub-zone wins over its parent for the same prefix or address.
    """
    from ..models import Zone

    vrf_id = vrf.pk if vrf else None
    networks, addresses = {}, {}
    zones = Zone.objects.filter(site=site).select_related('parent').prefetch_related(
        'prefixes', 'devices__primary_ip4', 'virtual_machines__primary_ip4')
    for zone in sorted(zones, key=_depth):
        for prefix in zone.prefixes.all():
            if prefix.vrf_id == vrf_id:
                networks[str(prefix.prefix)] = zone.name
        for asset in list(zone.devices.all()) + list(zone.virtual_machines.all()):
            ip = asset.primary_ip4
            if ip is not None and ip.vrf_id == vrf_id and ip.address.version == 4:
                addresses[str(ip.address.ip)] = zone.name
    return ZoneMap(networks, addresses)
