import csv
import ipaddress
import json
from contextlib import nullcontext
from pathlib import Path

from django.core.management.base import CommandError
from django.db import transaction
from django.db.models import Q

from dcim.models import Site
from ipam.models import VRF

from netbox_ot.branching import BranchCommand, change_logging, changelog_user
from netbox_ot.importers import zeek
from netbox_ot.importers.netbox_zones import zone_map_from_netbox
from netbox_ot.importers.observations import (
    UNKNOWN_COLUMNS,
    UNKNOWN_IMPORT_FILES,
    apply_plan,
    build_plan,
    inside_zone_advice,
    unknown_assets,
    unknown_import_rows,
    with_netbox_levels,
)


class Command(BranchCommand):
    help = ('Import zones, flows, Purdue levels and industrial services from observation files '
            '(docs/import-format.md) or from Zeek logs (with or without the CISA ICSNPP parsers)')
    follows_settings = True

    def writes(self, options):
        return not options.get('dry_run')

    def add_arguments(self, parser):
        parser.add_argument('directory', help='Directory holding assets.json, flows.json and optionally summary.json, '
                                              'or Zeek logs (conn.log, modbus.log, s7comm.log, ...)')
        parser.add_argument('--format', choices=('auto', 'observations', 'zeek'), default='auto',
                            help='Input format (default: Zeek when the directory holds a conn log)')
        parser.add_argument('--zone-map', metavar='CSV',
                            help='Zeek only: "network,zone[,purdue_level][,type]" lines placing addresses in zones, '
                                 'on top of the zones NetBox already has for the site')
        parser.add_argument('--suggest-zone-map', metavar='CSV',
                            help='Zeek only: list the networks the logs hold (per /24, with hosts and services), '
                                 'write a draft zone map for those no zone holds yet to this file, and stop. Edit '
                                 'it, then import with --zone-map')
        parser.add_argument('--unknown-report', metavar='CSV',
                            help='Write the observed hosts that match no device or VM in NetBox to this CSV file')
        parser.add_argument('--unknown-import', metavar='DIR',
                            help='Write the unknown hosts inside a zone as NetBox bulk-import files (devices, '
                                 'interfaces, IP addresses) to this directory; fill in role and device type, then '
                                 'import them in NetBox')
        parser.add_argument('--unknown-role', metavar='NAME',
                            help='With --unknown-import: device role (name or slug) for the hosts whose role the '
                                 'source does not name or names differently from NetBox')
        parser.add_argument('--unknown-device-type', metavar='MODEL',
                            help='With --unknown-import: device type (model or slug) for every host, e.g. a '
                                 'placeholder type "Unknown" to replace later')
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
        defaults = self._unknown_defaults(options)
        fmt = options['format']
        if fmt == 'auto':
            fmt = 'zeek' if zeek.is_zeek_directory(src) else 'observations'
        if options['suggest_zone_map']:
            if fmt != 'zeek':
                raise CommandError('--suggest-zone-map is for Zeek logs')
            return self._suggest_zone_map(src, site, vrf, options['zone_map'], options['suggest_zone_map'])
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
        user = changelog_user(options['user'])
        if isinstance(data.get('assets'), list) and all(isinstance(a, dict) for a in data['assets']):
            data['assets'], from_netbox = with_netbox_levels(data['assets'], site, vrf)
            if from_netbox:
                self.stdout.write(f'Purdue levels from NetBox for {from_netbox} asset(s) the input gives none for')

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
        for zone, why in plan.not_split.items():
            self.stdout.write(self.style.WARNING(f'--split "{zone}": not split, {why}'))
        if plan.inside:
            self.stdout.write('Industrial traffic inside a zone (flows run between zones, so this is not on the '
                              'access map):')
            for iz in plan.inside.values():
                senders = len(iz.senders)
                line = f'  {iz.zone}: {iz.requests} request(s) from {senders} host(s)'
                if iz.modifying:
                    who = ', '.join(sorted(iz.modifying_senders, key=ipaddress.ip_address)[:5])
                    line += f', {iz.modifying} of them write/control/program (from {who})'
                self.stdout.write(self.style.WARNING(line) if iz.modifying else line)
                self.stdout.write(f'    {inside_zone_advice(iz)}')

        # A dry run skips event tracking: no change log entries and no webhooks for rolled-back work
        tracking = nullcontext() if options['dry_run'] else change_logging(user)
        with transaction.atomic(using=self.db_alias), tracking:
            stats = apply_plan(plan, site, vrf=vrf, log=lambda m: self.stdout.write(f'  {m}'))
            if options['dry_run']:
                transaction.set_rollback(True, using=self.db_alias)
        for k, v in sorted(stats.items()):
            self.stdout.write(f'{k}: {v}')
        self._report_unknown(plan, site, vrf, options['unknown_report'], options['unknown_import'], defaults)
        self.stdout.write(self.style.WARNING('Dry run: nothing saved') if options['dry_run']
                          else self.style.SUCCESS(f'Done (change log user: {user})'))

    def _zone_map(self, site, vrf, zone_map_file):
        zone_map = zone_map_from_netbox(site, vrf)
        if zone_map_file:
            try:
                zone_map = zeek.ZoneMap.from_csv(zone_map_file, base=zone_map)
            except (OSError, ValueError) as e:
                raise CommandError(f'Cannot read zone map: {e}')
        return zone_map

    def _logs(self, src):
        logs = zeek.read_logs(src)
        if 'conn' not in logs:
            raise CommandError(f'No conn log in {src}')
        return logs

    def _survey(self, logs, zone_map):
        rows, public = zeek.survey(logs, zone_map)
        self.stdout.write('Networks in the conn log (per /24):')
        for line in zeek.survey_lines(rows, public):
            self.stdout.write(f'  {line}')
        return rows

    def _suggest_zone_map(self, src, site, vrf, zone_map_file, path):
        rows = self._survey(self._logs(src), self._zone_map(site, vrf, zone_map_file))
        lines = zeek.write_zone_map_draft(rows, path)
        if lines:
            self.stdout.write(self.style.SUCCESS(
                f'Draft zone map with {lines} network(s) written to {path}: name the zones, give their Purdue level '
                f'and type, then run ot_import {src} --site {site.slug} --zone-map {path} --dry-run'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Every network seen is already in a zone; nothing written to {path}'))

    def _read_zeek(self, src, site, vrf, zone_map_file):
        zone_map = self._zone_map(site, vrf, zone_map_file)
        logs = self._logs(src)
        if not zone_map.networks and not zone_map.addresses:
            # A first visit: show what the capture holds rather than stop at "no zone"
            self._survey(logs, zone_map)
            raise CommandError(
                f'No zone to place these addresses in yet: {site} has no zones with prefixes or members in NetBox. '
                f'Run again with --suggest-zone-map zones.csv for a draft zone map of the networks above, edit it, '
                f'and import with --zone-map zones.csv')
        assets, flows, summary = zeek.to_observations(logs, zone_map, captures=[src.name])
        # Streams the import does not use are never read
        streams = ', '.join(f'{name} ({records.count})' for name, records in sorted(logs.items())
                            if records.count is not None)
        self.stdout.write(f'Zeek logs: {streams}')
        return {'assets': assets, 'flows': flows, 'summary': summary}

    def _unknown_defaults(self, options):
        from dcim.models import DeviceRole, DeviceType

        found = {}
        for option, model, fields in (('unknown_role', DeviceRole, ('name', 'slug')),
                                      ('unknown_device_type', DeviceType, ('model', 'slug'))):
            value = options.get(option)
            if not value:
                continue
            if not options.get('unknown_import'):
                raise CommandError(f"--{option.replace('_', '-')} goes with --unknown-import")
            matches = list(model.objects.filter(Q(**{fields[0]: value}) | Q(**{fields[1]: value}))[:2])
            if len(matches) != 1:
                raise CommandError(f"--{option.replace('_', '-')} {value!r}: " + (
                    'not found in NetBox' if not matches else 'ambiguous; give the slug'))
            found[option] = matches[0]
        return found

    def _report_unknown(self, plan, site, vrf, path, import_dir, defaults=None):
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
            defaults = defaults or {}
            files, conflicts = unknown_import_rows(plan, site, vrf, role=defaults.get('unknown_role'),
                                                   device_type=defaults.get('unknown_device_type'))
            target = Path(import_dir)
            target.mkdir(parents=True, exist_ok=True)
            for name, columns in UNKNOWN_IMPORT_FILES:
                with open(target / name, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=columns)
                    writer.writeheader()
                    writer.writerows(files[name])
            devices = files['1-devices.csv']
            missing = [column for column in ('role', 'manufacturer', 'device_type')
                       if any(not d[column] for d in devices)]
            todo = (f"fill in {', '.join(missing)} in 1-devices.csv (names as NetBox shows them, not slugs; the "
                    f"description says what the capture saw), " if missing else '')
            if conflicts:
                where = 'the global table' if vrf is None else f'VRF {vrf}'
                self.stdout.write(self.style.WARNING(
                    f'{len(conflicts)} address(es) already exist in {where} and are left out of 3-ip-addresses.csv '
                    f'(NetBox refuses duplicates there):'))
                for ip, holder in conflicts[:10]:
                    self.stdout.write(f'  {ip}: {holder}')
                if len(conflicts) > 10:
                    self.stdout.write(f'  ... and {len(conflicts) - 10} more')
                if vrf is None:
                    self.stdout.write('  Is this another plant on the same addresses? Give each plant its own VRF and '
                                      'import with --vrf.')
            self.stdout.write(f"Bulk-import files for {len(devices)} unknown host(s) written to "
                              f'{target}: {todo}import the '
                              f'files in order in NetBox, then run this import again')
