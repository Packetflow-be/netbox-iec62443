from django.core.management.base import CommandError
from django.db.models import Q

from dcim.models import Device, Site
from virtualization.models import VirtualMachine

from netbox_ot.branching import BranchCommand
from netbox_ot.models import Flow
from netbox_ot.rules import build_rules, rules_csv, rules_json


class Command(BranchCommand):
    help = 'Export vendor-neutral firewall rules from the flows people allowed (CSV or JSON)'

    def add_arguments(self, parser):
        parser.add_argument('--site', help='Slug of the site whose flows to export (default: all sites)')
        parser.add_argument('--device', help='Only flows whose conduit this device or VM (name) enforces')
        parser.add_argument('--include-denied', action='store_true',
                            help='Also export not-allowed and expired flows as deny rules')
        parser.add_argument('--format', choices=('csv', 'json'), default='csv')
        parser.add_argument('--output', help='Write to this file instead of standard output')

    def handle(self, *args, **options):
        flows = Flow.objects.all()
        if options['site']:
            try:
                site = Site.objects.get(slug=options['site'])
            except Site.DoesNotExist:
                raise CommandError(f"Site {options['site']!r} not found")
            flows = flows.filter(Q(source_zone__site=site) | Q(destination_zone__site=site))
        enforcer = None
        if options['device']:
            enforcer = Device.objects.filter(name=options['device']).first() or \
                VirtualMachine.objects.filter(name=options['device']).first()
            if enforcer is None:
                raise CommandError(f"No device or VM named {options['device']!r}")
        rules, skipped = build_rules(flows, enforced_by=enforcer, include_denied=options['include_denied'])
        text = rules_csv(rules) if options['format'] == 'csv' else rules_json(rules, skipped)
        if options['output']:
            with open(options['output'], 'w', encoding='utf-8', newline='') as f:
                f.write(text)
        else:
            self.stdout.write(text, ending='')
        not_exported = ', '.join(f'{n} {reason}' for reason, n in sorted(skipped.items()))
        self.stderr.write(f'{len(rules)} rules' + (f'; not exported: {not_exported}' if not_exported else ''))
