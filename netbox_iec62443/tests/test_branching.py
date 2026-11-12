"""
The management commands and the settings page with and without netbox-branching.

Most of this needs netbox-branching installed (CI has a job for it, see .github/ci/configuration_branching.py);
without it only the fallbacks are tested.
"""
import json
import tempfile
from io import StringIO
from pathlib import Path
from unittest import skipIf, skipUnless

from django.apps import apps
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from core.models import ObjectChange
from dcim.models import Site
from ipam.models import Prefix
from users.models import User

from netbox_iec62443.models import Flow, PluginSettings, Zone
from netbox_iec62443.tests.test_importer import ASSETS, FLOWS, SUMMARY, make_asset

BRANCHING = apps.is_installed('netbox_branching')
DEMO_SITE = 'iec62443-demo'


def _write_observations(directory):
    for name, data in (('assets', ASSETS), ('flows', FLOWS), ('summary', SUMMARY)):
        Path(directory, f'{name}.json').write_text(json.dumps(data))


def _run(command, *args):
    out, err = StringIO(), StringIO()
    call_command(command, *args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


class PluginSettingsTest(TestCase):

    def test_branching_needs_a_default_branch(self):
        with self.assertRaises(ValidationError):
            PluginSettings(branching_enabled=True).full_clean()
        PluginSettings(branching_enabled=True, default_branch='trial').full_clean()

    def test_load_creates_one_row(self):
        self.assertIsNone(PluginSettings.objects.first())
        self.assertEqual(PluginSettings.load().pk, PluginSettings.load().pk)
        self.assertEqual(PluginSettings.objects.count(), 1)

    def test_branch_and_main_exclude_each_other(self):
        with self.assertRaisesRegex(CommandError, 'exclude each other'):
            _run('iec62443_demo', '--branch', 'trial', '--main')

    @skipIf(BRANCHING, 'netbox-branching is installed')
    def test_settings_ignored_without_netbox_branching(self):
        # Left behind from an install that had netbox-branching: there is no branch to go to, so main it is
        PluginSettings.objects.create(branching_enabled=True, default_branch='trial', protect_main=True)
        out, err = _run('iec62443_demo')
        self.assertTrue(Site.objects.filter(slug=DEMO_SITE).exists())
        self.assertEqual(err, '')

    @skipIf(BRANCHING, 'netbox-branching is installed')
    def test_settings_page_needs_netbox_branching(self):
        self.client.force_login(User.objects.create_superuser('admin'))
        self.assertEqual(self.client.get(reverse('plugins:netbox_iec62443:settings')).status_code, 404)

    @skipUnless(BRANCHING, 'needs netbox-branching')
    def test_settings_are_not_branched(self):
        from netbox_branching.utilities import supports_branching
        self.assertFalse(supports_branching(PluginSettings))
        self.assertTrue(supports_branching(Zone))


@skipUnless(BRANCHING, 'needs netbox-branching')
class PluginSettingsViewTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        from netbox_branching.models import Branch
        # Rows only: the page lists branches, it does not need their schemas
        for name, status in (('trial', 'ready'), ('old', 'merged')):
            Branch(name=name, status=status).save(provision=False)

    def setUp(self):
        self.url = reverse('plugins:netbox_iec62443:settings')

    def test_needs_permission(self):
        self.client.force_login(User.objects.create_user('viewer'))
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_lists_ready_branches_and_saves(self):
        self.client.force_login(User.objects.create_superuser('admin'))
        response = self.client.get(self.url)
        self.assertContains(response, '<option value="trial"')
        self.assertNotContains(response, '<option value="old"')

        response = self.client.post(self.url, {'branching_enabled': 'on', 'default_branch': 'trial',
                                               'protect_main': 'on'})
        self.assertRedirects(response, self.url)
        saved = PluginSettings.objects.get()
        self.assertEqual((saved.branching_enabled, saved.default_branch, saved.protect_main), (True, 'trial', True))
        self.assertEqual(saved.updated_by, 'admin')

    def test_rejects_a_branch_that_is_not_ready(self):
        self.client.force_login(User.objects.create_superuser('admin'))
        response = self.client.post(self.url, {'branching_enabled': 'on', 'default_branch': 'old'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PluginSettings.objects.filter(default_branch='old').exists())
        response = self.client.post(self.url, {'branching_enabled': 'on', 'default_branch': ''})
        self.assertContains(response, 'Pick the branch')

    def test_keeps_showing_a_branch_that_is_gone(self):
        PluginSettings.objects.create(branching_enabled=True, default_branch='old')
        self.client.force_login(User.objects.create_superuser('admin'))
        self.assertContains(self.client.get(self.url), 'old (no longer ready)')


@skipUnless(BRANCHING, 'needs netbox-branching')
class BranchCommandTest(TransactionTestCase):
    """Against a real, provisioned branch: what a command writes lands there and main is untouched."""
    serialized_rollback = True

    def setUp(self):
        from netbox_branching.models import Branch
        User.objects.create_superuser('admin')
        site = Site.objects.create(name='Demo', slug='demo')
        for a in ASSETS:
            make_asset(f"dev-{a['ip']}", a['ip'], site)
        for net in ('10.10.10.0/24', '192.168.1.0/24', '192.168.2.0/24'):
            Prefix.objects.create(prefix=net, scope=site)
        # The branch is a copy of main as it is now, assets included
        self.branch = Branch(name='trial')
        self.branch.save(provision=False)
        self.branch.provision(user=None)
        self.branch.refresh_from_db()

    def tearDown(self):
        self.branch.delete()  # drops the branch's schema

    def in_branch(self, queryset_fn):
        from netbox_branching.utilities import activate_branch
        with activate_branch(self.branch):
            return queryset_fn()

    def test_import_into_a_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_observations(tmp)
            _, err = _run('iec62443_import', tmp, '--site', 'demo', '--branch', 'trial', '--dry-run')
            self.assertIn('Working in branch "trial"', err)
            self.assertEqual(self.in_branch(lambda: Zone.objects.count()), 0)

            _run('iec62443_import', tmp, '--site', 'demo', '--branch', 'trial')

        self.assertEqual(Zone.objects.count(), 0)
        self.assertEqual(Flow.objects.count(), 0)
        self.assertGreater(self.in_branch(lambda: Zone.objects.count()), 0)
        self.assertGreater(self.in_branch(lambda: Flow.objects.count()), 0)
        # Change logged in the branch, so its Diff and Changes ahead tabs show the import
        self.assertTrue(self.in_branch(
            lambda: ObjectChange.objects.filter(changed_object_type__model='zone').exists()
        ))

        def on_plugin_objects(out):
            return [f for f in json.loads(out) if f['object'].startswith('netbox_iec62443.')]

        out, _ = _run('iec62443_check', '--site', 'demo', '--branch', 'trial', '--json', '--fail-on', 'never')
        self.assertTrue(on_plugin_objects(out))
        out, _ = _run('iec62443_check', '--site', 'demo', '--json', '--fail-on', 'never')
        self.assertEqual(on_plugin_objects(out), [])

    def test_unknown_or_unready_branch(self):
        with self.assertRaisesRegex(CommandError, "'nope' not found .*trial"):
            _run('iec62443_check', '--branch', 'nope')

    def test_default_branch_and_guard(self):
        PluginSettings.objects.create(branching_enabled=True, default_branch='trial', protect_main=True)

        _, err = _run('iec62443_demo')
        self.assertIn('default branch in IEC 62443 > Settings', err)
        self.assertFalse(Site.objects.filter(slug=DEMO_SITE).exists())
        self.assertTrue(self.in_branch(lambda: Site.objects.filter(slug=DEMO_SITE).exists()))

        # The reading commands stay on main without --branch
        _, err = _run('iec62443_check', '--fail-on', 'never')
        self.assertIn('Working in main', err)

        # The guard holds against --main too; a dry run is not a write
        with self.assertRaisesRegex(CommandError, 'refuse imports into main'):
            _run('iec62443_demo', '--main')
        with tempfile.TemporaryDirectory() as tmp:
            _write_observations(tmp)
            _run('iec62443_import', tmp, '--site', 'demo', '--main', '--dry-run')
            with self.assertRaisesRegex(CommandError, 'refuse imports into main'):
                _run('iec62443_import', tmp, '--site', 'demo', '--main')

        PluginSettings.objects.update(protect_main=False)
        _, err = _run('iec62443_demo', '--main')
        self.assertIn('Working in main', err)
        self.assertTrue(Site.objects.filter(slug=DEMO_SITE).exists())

    def test_merge_brings_logged_changes_to_main(self):
        _run('iec62443_demo', '--branch', 'trial')
        self.assertFalse(Site.objects.filter(slug=DEMO_SITE).exists())
        self.branch.merge(user=User.objects.get(username='admin'), commit=True)
        site = Site.objects.get(slug=DEMO_SITE)
        self.assertTrue(Zone.objects.filter(site=site).exists())
        self.assertTrue(Flow.objects.filter(destination_zone__site=site).exists())
