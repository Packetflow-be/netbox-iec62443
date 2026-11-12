"""
Optional support for the netbox-branching plugin in the management commands.

A management command runs outside a web request, so no branch is active and it reads and writes main.
`BranchCommand` adds `--branch NAME`: the whole command then runs with that branch active, and `self.db_alias`
names the database connection its transactions must use (the branch has a connection of its own).

Commands that write (`ot_import`, `ot_demo`) also follow the plugin settings (OT > Settings):
with "use a branch for imports" on they run in the default branch unless given `--branch` or `--main`, and with
"refuse imports into main" on they will not write to main at all.
"""
import uuid
from contextlib import contextmanager, nullcontext

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError, OutputWrapper
from django.db import DEFAULT_DB_ALIAS


def branching_installed():
    return apps.is_installed('netbox_branching')


def branch_names(ready_only=False):
    """Names of the existing branches (only those ready to work in, with `ready_only`); [] without the plugin."""
    if not branching_installed():
        return []
    from netbox_branching.models import Branch
    return sorted(b.name for b in Branch.objects.all() if b.ready or not ready_only)


def plugin_settings():
    """The saved settings, or None while nobody has saved any (reading never creates the row)."""
    from .models import PluginSettings
    return PluginSettings.objects.order_by('pk').first()


def changelog_user(username=None, required=True):
    """The user a command's changes are logged under: `username`, or the first superuser (None if not required)."""
    from users.models import User
    users = User.objects.filter(username=username) if username else \
        User.objects.filter(is_superuser=True).order_by('pk')
    user = users.first()
    if user is None and (required or username):
        raise CommandError(f'User {username!r} not found' if username else 'No user for the change log (use --user)')
    return user


def change_logging(user):
    """
    Record what the block saves in NetBox's change log under `user`, as a web request would. In a branch that is
    what netbox-branching shows in the branch's diff and replays on a merge: unlogged writes would never reach main.
    """
    from netbox.context_managers import event_tracking
    from utilities.request import NetBoxFakeRequest
    if user is None:
        return nullcontext()
    return event_tracking(NetBoxFakeRequest({'id': uuid.uuid4(), 'user': user, 'META': {}, 'path': '', 'GET': {},
                                             'POST': {}, 'FILES': {}}))


@contextmanager
def command_branch(name):
    """Activate the branch `name` and yield its database alias; without a name, yield the default alias (main)."""
    if not name:
        yield DEFAULT_DB_ALIAS
        return
    if not branching_installed():
        raise CommandError('--branch needs the netbox-branching plugin, which is not installed (or not in PLUGINS)')
    from netbox_branching.models import Branch
    from netbox_branching.utilities import activate_branch

    branch = Branch.objects.filter(name=name).first()
    if branch is None:
        names = ', '.join(branch_names()) or 'none'
        raise CommandError(f'Branch {name!r} not found (branches: {names})')
    if not branch.ready:
        raise CommandError(f'Branch {name!r} is not ready (status: {branch.status}); it must be provisioned, '
                           f'migrated and not merged')
    with activate_branch(branch):
        yield branch.connection_name


class BranchCommand(BaseCommand):
    """
    A management command with `--branch NAME` (and `--main`). Use `self.db_alias` for transactions.

    A command that writes sets `follows_settings = True`: it then runs in the default branch from the plugin
    settings when one is set, and respects "refuse imports into main". `writes(options)` says whether this run
    changes anything (a dry run does not).
    """

    db_alias = DEFAULT_DB_ALIAS
    follows_settings = False

    def writes(self, options):
        return self.follows_settings

    def create_parser(self, prog_name, subcommand, **kwargs):
        parser = super().create_parser(prog_name, subcommand, **kwargs)
        parser.add_argument('--branch', metavar='NAME',
                            help='Run in this branch (netbox-branching plugin) instead of main')
        if self.follows_settings:
            parser.add_argument('--main', action='store_true',
                                help='Run in main even when the plugin settings name a default branch')
        return parser

    def resolve_branch(self, options):
        """The branch to run in (None for main) and why, applying the plugin settings to a command that writes."""
        name = options.get('branch')
        if name and options.get('main'):
            raise CommandError('--branch and --main exclude each other')
        if name:
            return name, None
        if not self.follows_settings or not branching_installed():
            return None, None
        saved = plugin_settings()
        if saved is None:
            return None, None
        if saved.branching_enabled and saved.default_branch and not options.get('main'):
            return saved.default_branch, 'the default branch in OT > Settings'
        if saved.protect_main and self.writes(options):
            raise CommandError(
                'Imports into main are switched off in OT > Settings ("refuse imports into main"). '
                'Name a branch with --branch, or switch that setting off.'
            )
        return None, None

    def execute(self, *args, **options):
        if options.get('stderr'):
            # BaseCommand.execute() does this too, but the notice below is written before it runs
            self.stderr = OutputWrapper(options['stderr'])
        name, reason = self.resolve_branch(options)
        if name:
            # To stderr, so output that is piped or parsed (--json, rules as CSV) stays clean
            why = f' ({reason})' if reason else ''
            self.stderr.write(f'Working in branch "{name}"{why}; main is not touched', self.style.NOTICE)
        elif branching_installed():
            self.stderr.write('Working in main', self.style.NOTICE)
        with command_branch(name) as self.db_alias:
            return super().execute(*args, **options)
