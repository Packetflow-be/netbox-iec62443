import csv
import json
import uuid
from contextlib import nullcontext
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from dcim.models import Site
from ipam.models import VRF
from netbox.context_managers import event_tracking
from users.models import User
from utilities.request import NetBoxFakeRequest

from netbox_ot.importers import zeek
from netbox_ot.importers.netbox_zones import zone_map_from_netbox
from netbox_ot.importers.observations import (
    UNKNOWN_COLUMNS,
    UNKNOWN_IMPORT_FILES,
    apply_plan,
    build_plan,
    unknown_assets,
    unknown_import_rows,
)


class Command(BaseCommand):
    help = ('Import zones, flows, Purdue levels and industrial services from observation files '
            '(docs/import-format.md) or from Zeek logs (with or without the CISA ICSNPP parsers)')

    def add_arguments(self, parser):
        parser.add_argument('directory', help='Directory holding assets.json, flows.json and optionally summary.json, '
                                              'or Zeek logs (conn.log, modbus.log, s7comm.log, ...)')
        parser.add_argument('--format', choices=('auto', 'observations', 'zeek'), default='auto',
                            help='Input format (default: Zeek when the directory holds a conn log)')
        parser.add_argument('--zone-map', metavar='CSV',
                            help='Zeek only: "network,zone[,purdue_level][,type]" lines placing addresses in zones, '
                                 'on top of the zones NetBox already has for the site')
        parser.add_argument('--unknown-report', metavar='CSV',
                            help='Write the observed hosts that match no device or VM in NetBox to this CSV file')
        parser.add_argument('--unknown-import', metavar='DIR',
                            help='Write the unknown hosts inside a zone as NetBox bulk-import files (devices, '
                                 'interfaces, IP addresses) to this directory; fill in role and device type, then '
                                 'import them in NetBox')
        parser.add_argument('--site', required=True, help='Slug of the site the zones belong to')
        parser.add_argument('--user', help='Username recorded in the change log (default: first superuser)')
        parser.add_argument('--dry-run', action='store_true', help='Show what would change, then roll back')
        parser.add_argument('--vrf', metavar='NAME_OR_RD',
                            help='VRF the observed addresses live in (default: the global table). Devices, VMs and '
                                 'prefixes are only matched within --site and this VRF')
        parser.add_argument('--outside-zone', default='Outside',
                            help='Name of the zone for addresses not listed in assets.json (default: Outside)')
        parser.add_argument('--split', action='append', default=[], metavar='ZONE',
                            help='Split this zone per Purdue band: control (0-1), supervisory (2), operations (3+) '
                                 '(repeatable)')
        parser.add_argument('--split-all', action='store_true', help='Split every zone that mixes Purdue bands')

    def handle(self, *args, **options):
        src = Path(options['directory'])
        if not src.is_dir():
            raise CommandError(f'{src} is not a directory')
        try:
            site = Site.objects.get(slug=options['site'])
        except Site.DoesNotExist:
            raise CommandError(f"Site {options['site']!r} not found")
        vrf = None
        if options['vrf']:
            vrfs = list(VRF.objects.filter(Q(name=options['vrf']) | Q(rd=options['vrf']))[:2])
            if len(vrfs) != 1:
                raise CommandError(f"VRF {options['vrf']!r} " + ('not found' if not vrfs else
                                                                 'is ambiguous; give its route distinguisher'))
            vrf = vrfs[0]
        fmt = options['format']
        if fmt == 'auto':
            fmt = 'zeek' if zeek.is_zeek_directory(src) else 'observations'
        if fmt == 'zeek':
            data = self._read_zeek(src, site, vrf, options['zone_map'])
        else:
            if options['zone_map']:
                raise CommandError('--zone-map is for Zeek logs; observation files name the zone of every asset')
            try:
                data = {name: json.loads((src / f'{name}.json').read_text()) for name in ('assets', 'flows')}
                summary = src / 'summary.json'
                data['summary'] = json.loads(summary.read_text()) if summary.exists() else {}
            except (OSError, ValueError) as e:
                raise CommandError(f'Cannot read input: {e}')
        users = User.objects.filter(username=options['user']) if options['user'] else \
            User.objects.filter(is_superuser=True).order_by('pk')
        user = users.first()
        if user is None:
            raise CommandError('No user for the change log (use --user)')

        try:
            plan = build_plan(data['assets'], data['flows'], data['summary'], outside_zone=options['outside_zone'],
                              split_zones=True if options['split_all'] else options['split'])
        except ValueError as e:
            raise CommandError(f'Invalid input: {e}')
        self.stdout.write(f'Plan: {len(plan.zones)} zones, {len(plan.flows)} flows, '
                          f'{len(plan.asset_levels)} assets with a Purdue level')
        if plan.unidentified_ports:
            self.stdout.write('Open OT ports without an identified protocol (no service created; name the protocol '
                              'under "services" in assets.json, or add the service by hand):')
            for op in plan.unidentified_ports:
                self.stdout.write(f"  {op.ip} port {op.port}: {' or '.join(op.candidates)}?")

        request = NetBoxFakeRequest({'id': uuid.uuid4(), 'user': user, 'META': {}, 'path': '', 'GET': {},
                                     'POST': {}, 'FILES': {}})
        # A dry run skips event tracking: no change log entries and no webhooks for rolled-back work
        tracking = nullcontext() if options['dry_run'] else event_tracking(request)
        with transaction.atomic(), tracking:
            stats = apply_plan(plan, site, vrf=vrf, log=lambda m: self.stdout.write(f'  {m}'))
            if options['dry_run']:
                transaction.set_rollback(True)
        for k, v in sorted(stats.items()):
            self.stdout.write(f'{k}: {v}')
        self._report_unknown(plan, site, vrf, options['unknown_report'], options['unknown_import'])
        self.stdout.write(self.style.WARNING('Dry run: nothing saved') if options['dry_run']
                          else self.style.SUCCESS(f'Done (change log user: {user})'))

    def _read_zeek(self, src, site, vrf, zone_map_file):
        zone_map = zone_map_from_netbox(site, vrf)
        if zone_map_file:
            try:
                zone_map = zeek.ZoneMap.from_csv(zone_map_file, base=zone_map)
            except (OSError, ValueError) as e:
                raise CommandError(f'Cannot read zone map: {e}')
        if not zone_map.networks and not zone_map.addresses:
            raise CommandError(f'No zone to place addresses in: give the zones of {site} prefixes or members in '
                               f'NetBox, or pass --zone-map')
        logs = zeek.read_logs(src)
        if 'conn' not in logs:
            raise CommandError(f'No conn log in {src}')
        assets, flows, summary = zeek.to_observations(logs, zone_map, captures=[src.name])
        streams = ', '.join(f'{name} ({len(records)})' for name, records in sorted(logs.items()))
        self.stdout.write(f'Zeek logs: {streams}')
        return {'assets': assets, 'flows': flows, 'summary': summary}

    def _report_unknown(self, plan, site, vrf, path, import_dir):
        rows = unknown_assets(plan, site, vrf)
        in_zones = [r for r in rows if r['zone']]
        self.stdout.write(f'Observed hosts not in NetBox: {len(rows)} ({len(in_zones)} inside a zone)')
        for row in in_zones[:20]:
            seen = f" seen {row['first_seen'][:10]}..{row['last_seen'][:10]}" if row['first_seen'] else ''
            serves = f", serves {row['serves']}" if row['serves'] else ''
            self.stdout.write(f"  {row['ip']} in {row['zone']}: {row['peers']} peer(s){serves}{seen}")
        if len(in_zones) > 20:
            self.stdout.write(f'  ... and {len(in_zones) - 20} more')
        if path:
            with open(path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=UNKNOWN_COLUMNS)
                writer.writeheader()
                writer.writerows(rows)
            self.stdout.write(f'Report written to {path}')
        if import_dir:
            files = unknown_import_rows(plan, site, vrf)
            target = Path(import_dir)
            target.mkdir(parents=True, exist_ok=True)
            for name, columns in UNKNOWN_IMPORT_FILES:
                with open(target / name, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=columns)
                    writer.writeheader()
                    writer.writerows(files[name])
            self.stdout.write(f"Bulk-import files for {len(files['1-devices.csv'])} unknown host(s) written to "
                              f'{target}: fill in role, manufacturer and device_type in 1-devices.csv, import the '
                              f'files in order in NetBox, then run this import again')
