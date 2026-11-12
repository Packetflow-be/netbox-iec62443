import json

from django.core.management.base import BaseCommand, CommandError

from dcim.models import Site

from netbox_ot.checks import CHECKS, SEVERITIES, run_checks


class Command(BaseCommand):
    help = 'Run the IEC 62443 consistency checks; exits non-zero when findings reach --fail-on (for CI)'

    def add_arguments(self, parser):
        parser.add_argument('--site', help='Slug of the site to check (default: all sites)')
        parser.add_argument('--severity', action='append', choices=SEVERITIES,
                            help='Only report this severity (repeatable)')
        parser.add_argument('--check', action='append', choices=sorted(CHECKS),
                            help='Only run this check (repeatable)')
        parser.add_argument('--fail-on', choices=('error', 'warning', 'info', 'never'), default='error',
                            help='Exit with status 1 on a finding of this severity or worse (default: error)')
        parser.add_argument('--json', action='store_true', help='Print the findings as JSON')

    def handle(self, *args, **options):
        site = None
        if options['site']:
            try:
                site = Site.objects.get(slug=options['site'])
            except Site.DoesNotExist:
                raise CommandError(f"Site {options['site']!r} not found")
        findings = run_checks(site=site, checks=options['check'], severities=options['severity'])
        if options['json']:
            self.stdout.write(json.dumps([{
                'check': f.check, 'severity': f.severity, 'object': f'{f.obj._meta.label_lower}:{f.obj.pk}',
                'display': str(f.obj), 'message': f.message,
            } for f in findings], indent=2))
        else:
            for f in findings:
                self.stdout.write(f'{f.severity.upper():8} {f.check:30} {f.message}')
            counts = {s: sum(1 for f in findings if f.severity == s) for s in SEVERITIES}
            self.stdout.write(', '.join(f'{n} {s}' for s, n in counts.items()))
        if options['fail_on'] != 'never':
            worst = SEVERITIES[:SEVERITIES.index(options['fail_on']) + 1]
            if any(f.severity in worst for f in findings):
                raise SystemExit(1)
