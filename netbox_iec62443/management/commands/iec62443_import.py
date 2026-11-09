import json
import uuid
from contextlib import nullcontext
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from dcim.models import Site
from netbox.context_managers import event_tracking
from users.models import User
from utilities.request import NetBoxFakeRequest

from netbox_iec62443.importers.observations import apply_plan, build_plan


class Command(BaseCommand):
    help = 'Import zones, conduits, Purdue levels and industrial services from observation files (docs/import-format.md)'

    def add_arguments(self, parser):
        parser.add_argument('directory', help='Directory holding assets.json, flows.json and optionally summary.json')
        parser.add_argument('--site', required=True, help='Slug of the site the zones belong to')
        parser.add_argument('--user', help='Username recorded in the change log (default: first superuser)')
        parser.add_argument('--dry-run', action='store_true', help='Show what would change, then roll back')
        parser.add_argument('--rename', action='append', default=[], metavar='OLD=NEW',
                            help='Rename a zone from the input (repeatable), e.g. "Z5 Kantoor=Z5 Office"')
        parser.add_argument('--outside-zone', default='Outside',
                            help='Name of the zone for addresses outside the scanned floor (default: Outside)')
        parser.add_argument('--split', action='append', default=[], metavar='ZONE',
                            help='Split this zone per Purdue band: control (0-1), supervisory (2), operations (3+) '
                                 '(repeatable; input or renamed name)')
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
        users = User.objects.filter(username=options['user']) if options['user'] else \
            User.objects.filter(is_superuser=True).order_by('pk')
        user = users.first()
        if user is None:
            raise CommandError('No user for the change log (use --user)')

        renames = {}
        for item in options['rename']:
            old, sep, new = item.partition('=')
            if not sep or not old.strip() or not new.strip():
                raise CommandError(f'--rename expects OLD=NEW, got {item!r}')
            renames[old.strip()] = new.strip()
        plan = build_plan(data['assets'], data['flows'], data['summary'], renames=renames,
                          outside_zone=options['outside_zone'],
                          split_zones=True if options['split_all'] else options['split'])
        self.stdout.write(f'Plan: {len(plan.zones)} zones, {len(plan.conduits)} conduits, '
                          f'{len(plan.asset_levels)} assets with a Purdue level')

        request = NetBoxFakeRequest({'id': uuid.uuid4(), 'user': user, 'META': {}, 'path': '', 'GET': {},
                                     'POST': {}, 'FILES': {}})
        # A dry run skips event tracking: no change log entries and no webhooks for rolled-back work
        tracking = nullcontext() if options['dry_run'] else event_tracking(request)
        with transaction.atomic(), tracking:
            stats = apply_plan(plan, site, log=lambda m: self.stdout.write(f'  {m}'))
            if options['dry_run']:
                transaction.set_rollback(True)
        for k, v in sorted(stats.items()):
            self.stdout.write(f'{k}: {v}')
        self.stdout.write(self.style.WARNING('Dry run: nothing saved') if options['dry_run']
                          else self.style.SUCCESS(f'Done (change log user: {user})'))
