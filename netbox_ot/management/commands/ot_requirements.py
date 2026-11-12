from pathlib import Path

from django.core.management.base import CommandError
from django.db import transaction

from netbox_ot.branching import BranchCommand, change_logging, changelog_user
from netbox_ot.choices import RequirementEditionChoices
from netbox_ot.requirements import load_rows, load_shipped, read_rows


class Command(BranchCommand):
    help = ('Load the IEC 62443-3-3 system requirement identifiers the plugin ships, and with --csv the enhancements, '
            'security levels and wording from your own licensed copy of the standard')

    def add_arguments(self, parser):
        parser.add_argument('--csv', metavar='FILE',
                            help='identifier[,foundational_requirement][,security_level][,wording] per line, with a '
                                 'header row; empty cells leave stored values alone')
        parser.add_argument('--edition', default=RequirementEditionChoices.IEC_62443_3_3_2013,
                            choices=RequirementEditionChoices.values())
        parser.add_argument('--user', help='Record the changes under this user (default: the first superuser)')
        parser.add_argument('--dry-run', action='store_true', help='Show what would change, save nothing')

    def handle(self, *args, **options):
        rows = None
        if options['csv']:
            try:
                rows = read_rows(Path(options['csv']).read_text(encoding='utf-8-sig'))
            except (OSError, ValueError) as e:
                raise CommandError(f'Cannot read {options["csv"]}: {e}')
        user = changelog_user(options['user'], required=False)
        with transaction.atomic(using=self.db_alias), change_logging(None if options['dry_run'] else user):
            try:
                shipped = load_shipped(options['edition'])
                loaded = load_rows(rows, options['edition']) if rows is not None else {}
            except ValueError as e:
                raise CommandError(str(e))
            if options['dry_run']:
                transaction.set_rollback(True, using=self.db_alias)
        self.stdout.write(f"Identifiers shipped with the plugin: {shipped.get('created', 0)} created, "
                          f"{shipped.get('unchanged', 0)} already there")
        if rows is not None:
            self.stdout.write(f"{options['csv']}: {loaded.get('created', 0)} created, {loaded.get('updated', 0)} "
                              f"updated, {loaded.get('unchanged', 0)} unchanged")
        if options['dry_run']:
            self.stdout.write(self.style.WARNING('Dry run: nothing saved'))
