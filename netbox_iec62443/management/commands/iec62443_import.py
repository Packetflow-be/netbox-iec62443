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

from netbox_iec62443.importers.observations import apply_plan, build_plan


class Command(BaseCommand):
    help = ('Import zones, flows, Purdue levels and industrial services from observation files '
            '(docs/import-format.md)')

    def add_arguments(self, parser):
        parser.add_argument('directory', help='Directory holding assets.json, flows.json and optionally summary.json')
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
        try:
            data = {name: json.loads((src / f'{name}.json').read_text()) for name in ('assets', 'flows')}
            summary = src / 'summary.json'
            data['summary'] = json.loads(summary.read_text()) if summary.exists() else {}
        except (OSError, ValueError) as e:
            raise CommandError(f'Cannot read input: {e}')
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
        self.stdout.write(self.style.WARNING('Dry run: nothing saved') if options['dry_run']
                          else self.style.SUCCESS(f'Done (change log user: {user})'))
