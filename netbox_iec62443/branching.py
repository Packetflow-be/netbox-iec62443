"""
Optional support for the netbox-branching plugin in the management commands.

A management command runs outside a web request, so no branch is active and it reads and writes main.
`BranchCommand` adds `--branch NAME`: the whole command then runs with that branch active, and `self.db_alias`
names the database connection its transactions must use (the branch has a connection of its own).
"""
from contextlib import contextmanager

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS


@contextmanager
def command_branch(name):
    """Activate the branch `name` and yield its database alias; without a name, yield the default alias (main)."""
    if not name:
        yield DEFAULT_DB_ALIAS
        return
    if not apps.is_installed('netbox_branching'):
        raise CommandError('--branch needs the netbox-branching plugin, which is not installed (or not in PLUGINS)')
    from netbox_branching.models import Branch
    from netbox_branching.utilities import activate_branch

    branch = Branch.objects.filter(name=name).first()
    if branch is None:
        names = ', '.join(sorted(Branch.objects.values_list('name', flat=True))) or 'none'
        raise CommandError(f'Branch {name!r} not found (branches: {names})')
    if not branch.ready:
        raise CommandError(f'Branch {name!r} is not ready (status: {branch.status}); it must be provisioned, '
                           f'migrated and not merged')
    with activate_branch(branch):
        yield branch.connection_name


class BranchCommand(BaseCommand):
    """A management command with `--branch NAME`. Use `self.db_alias` for transactions."""

    db_alias = DEFAULT_DB_ALIAS

    def create_parser(self, prog_name, subcommand, **kwargs):
        parser = super().create_parser(prog_name, subcommand, **kwargs)
        parser.add_argument('--branch', metavar='NAME',
                            help='Run in this branch (netbox-branching plugin) instead of main')
        return parser

    def execute(self, *args, **options):
        name = options.get('branch')
        with command_branch(name) as self.db_alias:
            output = super().execute(*args, **options)
        if name:
            # To stderr, so output that is piped or parsed (--json, rules as CSV) stays clean
            self.stderr.write(f'Ran in branch "{name}"; main is untouched', self.style.NOTICE)
        return output
