"""IEC 62443-3-3 system requirements and their status per zone or conduit (#6)."""
import csv
import datetime
import io
import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase

from dcim.models import Site
from tenancy.models import Contact
from utilities.testing import APIViewTestCases, ViewTestCases, create_tags

from netbox_iec62443.checks import run_checks
from netbox_iec62443.models import Conduit, RequirementStatus, RiskAssessment, SystemRequirement, Zone
from netbox_iec62443.register import REQUIREMENT_COLUMNS, build_register, register_csv, register_json
from netbox_iec62443.requirements import SHIPPED, load_rows, load_shipped, normalise, read_rows
from netbox_iec62443.tests.test_views import PluginURLMixin


def requirement(identifier, fr='iac', level=None, parent=None):
    return SystemRequirement.objects.create(identifier=identifier, foundational_requirement=fr, security_level=level,
                                            parent=parent)


class ShippedIdentifiersTest(SimpleTestCase):
    """The copyright rule: the repository ships identifiers and foundational requirements, nothing else."""

    def test_identifiers_only(self):
        for path in SHIPPED.values():
            rows = read_rows(path.read_text(encoding='utf-8'))
            self.assertEqual({tuple(sorted(row)) for row in rows}, {('foundational_requirement', 'identifier')})
            self.assertTrue(all(row['identifier'].startswith('SR ') and ' RE ' not in row['identifier']
                                for row in rows))
            per_fr = {}
            for row in rows:
                per_fr[row['foundational_requirement']] = per_fr.get(row['foundational_requirement'], 0) + 1
            self.assertEqual(per_fr, {'iac': 13, 'uc': 12, 'si': 9, 'dc': 3, 'rdf': 4, 'tre': 2, 'ra': 8})

    def test_normalise(self):
        self.assertEqual(normalise('sr1.1re1'), 'SR 1.1 RE 1')
        self.assertEqual(normalise(' SR 7.8 '), 'SR 7.8')


class LoaderTest(TestCase):

    def test_shipped_is_idempotent(self):
        self.assertEqual(load_shipped(), {'created': 51})
        self.assertEqual(load_shipped(), {'unchanged': 51})
        self.assertEqual(SystemRequirement.objects.get(identifier='SR 7.8').foundational_requirement, 'ra')
        self.assertFalse(SystemRequirement.objects.exclude(wording='').exists())
        self.assertFalse(SystemRequirement.objects.filter(security_level__isnull=False).exists())

    def test_user_csv(self):
        load_shipped()
        text = ('# my licensed copy\n'
                'Identifier,SL,Wording\n'
                'SR 1.1 RE 1,2,Enhancement text\n'
                'SR 1.1,1,Requirement text\n'
                'SR 1.2,,\n')
        stats = load_rows(read_rows(text))
        self.assertEqual(stats, {'created': 1, 'updated': 1, 'unchanged': 1})
        enhancement = SystemRequirement.objects.get(identifier='SR 1.1 RE 1')
        self.assertEqual((enhancement.parent.identifier, enhancement.security_level, enhancement.wording,
                          enhancement.foundational_requirement), ('SR 1.1', 2, 'Enhancement text', 'iac'))
        # An empty cell leaves what is stored
        load_rows(read_rows('identifier,security_level,wording\nSR 1.1,,\n'))
        self.assertEqual(SystemRequirement.objects.get(identifier='SR 1.1').security_level, 1)

    def test_enhancement_creates_its_requirement(self):
        load_rows(read_rows('identifier\nSR 3.4 RE 1\n'))
        self.assertEqual(SystemRequirement.objects.get(identifier='SR 3.4 RE 1').parent.identifier, 'SR 3.4')

    def test_bad_input(self):
        for text, message in (
            ('name\nSR 1.1\n', 'identifier'),
            ('identifier\nFR 1\n', 'not a requirement identifier'),
            ('identifier,fr\nSR 1.1,xx\n', 'foundational requirement'),
            ('identifier,sl\nSR 1.1,5\n', 'security level'),
        ):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, message):
                load_rows(read_rows(text))

    def test_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, 'sl.csv')
            path.write_text('identifier,security_level\nSR 5.1,1\nSR 5.1 RE 1,2\n')
            out = StringIO()
            call_command('iec62443_requirements', '--csv', str(path), '--dry-run', stdout=out)
            self.assertIn('Dry run', out.getvalue())
            self.assertFalse(SystemRequirement.objects.exists())
            call_command('iec62443_requirements', '--csv', str(path), stdout=StringIO())
        self.assertEqual(SystemRequirement.objects.count(), 52)
        self.assertEqual(SystemRequirement.objects.get(identifier='SR 5.1').security_level, 1)


class ModelTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(name='Plant', slug='plant')
        cls.cell = Zone.objects.create(name='Cell', slug='cell', site=cls.site)
        cls.office = Zone.objects.create(name='Office', slug='office', site=cls.site)
        cls.conduit = Conduit.objects.create(name='Office - Cell', site=cls.site)
        cls.sr = requirement('SR 1.1')

    def test_requirement_rules(self):
        for kwargs, field in (
            ({'identifier': 'SR 1'}, 'identifier'),
            ({'identifier': 'SR 8.1'}, 'identifier'),
            ({'identifier': 'SR 2.1', 'foundational_requirement': 'iac'}, 'foundational_requirement'),
            ({'identifier': 'SR 1.1 RE 1'}, 'parent'),
            ({'identifier': 'SR 1.2 RE 1', 'parent': self.sr}, 'parent'),
            ({'identifier': 'SR 1.2', 'parent': self.sr}, 'parent'),
            ({'identifier': 'SR 1.2', 'security_level': 5}, 'security_level'),
        ):
            with self.subTest(**{k: str(v) for k, v in kwargs.items()}):
                with self.assertRaises(ValidationError) as ctx:
                    SystemRequirement(**kwargs).full_clean()
                self.assertIn(field, ctx.exception.message_dict)
        ok = SystemRequirement(identifier='SR 1.1 RE 1', parent=self.sr)
        ok.full_clean()
        self.assertEqual(ok.foundational_requirement, 'iac')

    def test_status_rules(self):
        with self.assertRaisesRegex(ValidationError, 'either a zone or a conduit'):
            RequirementStatus(zone=self.cell, conduit=self.conduit, requirement=self.sr, status='met').full_clean()
        with self.assertRaisesRegex(ValidationError, 'countermeasure'):
            RequirementStatus(zone=self.cell, requirement=self.sr, status='compensated').full_clean()
        other = RiskAssessment.objects.create(zone=self.office, assessed_on=datetime.date(2026, 1, 1))
        with self.assertRaisesRegex(ValidationError, 'another zone or conduit'):
            RequirementStatus(zone=self.cell, requirement=self.sr, status='met', risk_assessment=other).full_clean()
        RequirementStatus.objects.create(zone=self.cell, requirement=self.sr, status='met')
        RequirementStatus.objects.create(conduit=self.conduit, requirement=self.sr, status='met')
        with self.assertRaises(IntegrityError), transaction.atomic():
            RequirementStatus.objects.create(zone=self.cell, requirement=self.sr, status='not-met')


class RequirementChecksTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(name='Plant', slug='plant')
        cls.cell = Zone.objects.create(name='Cell', slug='cell', site=cls.site, sl_target=[2] * 7,
                                       sl_achieved=[2, 1, 1, 1, 1, 1, 1])
        cls.sr11 = requirement('SR 1.1', level=1)
        cls.sr12 = requirement('SR 1.2', level=2)
        cls.sr13 = requirement('SR 1.3', level=3)  # above the SL-T: does not apply
        cls.sr21 = requirement('SR 2.1', fr='uc', level=2)
        requirement('SR 2.2', fr='uc')  # no level loaded: never applies

    def _messages(self, check):
        return [f.message for f in run_checks(site=self.site, checks=[check])]

    def test_without_status(self):
        [message] = self._messages('requirements-without-status')
        self.assertIn('3 requirements apply at SL-T {2 2 2 2 2 2 2}', message)
        self.assertIn('SR 1.1, SR 1.2, SR 2.1', message)
        for sr in (self.sr11, self.sr12, self.sr21):
            RequirementStatus.objects.create(zone=self.cell, requirement=sr, status='met')
        self.assertEqual(self._messages('requirements-without-status'), [])

    def test_not_met_against_sl_a(self):
        RequirementStatus.objects.create(zone=self.cell, requirement=self.sr12, status='not-met')
        # SL-A in UC is 1, below SR 2.1's level 2: not met there is no contradiction
        RequirementStatus.objects.create(zone=self.cell, requirement=self.sr21, status='not-met')
        self.assertEqual(self._messages('requirement-not-met-for-sl-a'),
                         ['Cell claims SL-A 2 in IAC but SR 1.2 is not met'])

    def test_nothing_without_levels(self):
        SystemRequirement.objects.update(security_level=None)
        self.assertEqual(self._messages('requirements-without-status'), [])

    def test_register(self):
        RequirementStatus.objects.create(zone=self.cell, requirement=self.sr13, status='met', evidence='MFA')
        register = build_register(self.site)
        rows = [(r['zone'], r['requirement'], r['applies_at_sl_t'], r['status']) for r in register['requirements']]
        self.assertEqual(rows, [
            ('Cell', 'SR 1.1', 'yes', ''), ('Cell', 'SR 1.2', 'yes', ''), ('Cell', 'SR 1.3', 'no', 'Met'),
            ('Cell', 'SR 2.1', 'yes', ''),
        ])
        table = list(csv.reader(io.StringIO(register_csv(register, 'requirements'))))
        self.assertEqual(tuple(table[0]), REQUIREMENT_COLUMNS)
        data = register_json(register)
        json.dumps(data, default=str)  # no model objects left
        self.assertEqual(data['requirements'][2]['status_code'], 'met')


class SystemRequirementViewTest(PluginURLMixin, ViewTestCases.PrimaryObjectViewTestCase):
    model = SystemRequirement

    @classmethod
    def setUpTestData(cls):
        SystemRequirement.objects.bulk_create([
            SystemRequirement(identifier=f'SR 1.{n}', foundational_requirement='iac') for n in (1, 2, 3)
        ])
        tags = create_tags('Alpha', 'Bravo', 'Charlie')
        cls.form_data = {
            'edition': '3-3:2013',
            'identifier': 'SR 2.1',
            'foundational_requirement': 'uc',
            'security_level': 2,
            'wording': 'Text from my licensed copy',
            'description': 'Authorization enforcement',
            'tags': [t.pk for t in tags],
        }
        cls.csv_data = (
            'identifier,security_level',
            'SR 3.1,1',
            'SR 3.2,2',
            'SR 3.3,',
        )
        cls.csv_update_data = (
            'id,security_level,description',
            f'{SystemRequirement.objects.get(identifier="SR 1.1").pk},1,changed',
            f'{SystemRequirement.objects.get(identifier="SR 1.2").pk},2,changed',
            f'{SystemRequirement.objects.get(identifier="SR 1.3").pk},3,changed',
        )
        cls.bulk_edit_data = {'security_level': 3}


class RequirementStatusViewTest(PluginURLMixin, ViewTestCases.PrimaryObjectViewTestCase):
    model = RequirementStatus

    @classmethod
    def setUpTestData(cls):
        site = Site.objects.create(name='Site 1', slug='site-1')
        cell = Zone.objects.create(name='Cell', slug='cell', site=site)
        office = Zone.objects.create(name='Office', slug='office', site=site)
        conduit = Conduit.objects.create(name='Office - Cell', site=site)
        sr = [requirement(f'SR 1.{n}') for n in (1, 2, 3)]
        contact = Contact.objects.create(name='OT security lead')
        RequirementStatus.objects.bulk_create([
            RequirementStatus(zone=cell, requirement=sr[0], status='met'),
            RequirementStatus(zone=cell, requirement=sr[1], status='not-met'),
            RequirementStatus(conduit=conduit, requirement=sr[0], status='met'),
        ])
        tags = create_tags('Alpha', 'Bravo', 'Charlie')
        cls.form_data = {
            'zone': office.pk,
            'requirement': sr[2].pk,
            'status': 'compensated',
            'countermeasure': 'Jump host with MFA in front of the zone',
            'evidence': 'Firewall rule review 2026-11',
            'assessed_by': contact.pk,
            'assessed_on': datetime.date(2026, 11, 1),
            'tags': [t.pk for t in tags],
        }
        cls.csv_data = (
            'site,zone,conduit,requirement,status,countermeasure',
            'Site 1,Office,,SR 1.1,met,',
            'Site 1,Office,,SR 1.2,compensated,Jump host',
            'Site 1,,Office - Cell,SR 1.2,not-applicable,',
        )
        ids = list(RequirementStatus.objects.order_by('pk').values_list('pk', flat=True))
        cls.csv_update_data = (
            'id,status,description',
            f'{ids[0]},not-met,changed',
            f'{ids[1]},met,changed',
            f'{ids[2]},not-applicable,changed',
        )
        cls.bulk_edit_data = {'status': 'not-applicable'}


class SystemRequirementAPITest(APIViewTestCases.APIViewTestCase):
    model = SystemRequirement
    view_namespace = 'plugins-api:netbox_iec62443'
    graphql_base_name = 'iec62443_system_requirement'
    brief_fields = ['description', 'display', 'edition', 'id', 'identifier', 'url']
    bulk_update_data = {'security_level': 3}

    @classmethod
    def setUpTestData(cls):
        parent = requirement('SR 1.1')
        requirement('SR 1.2')
        requirement('SR 1.3')
        cls.create_data = [
            {'identifier': 'SR 4.1', 'security_level': 2},
            {'identifier': 'SR 4.2', 'foundational_requirement': 'dc', 'wording': 'From my copy'},
            {'identifier': 'SR 1.1 RE 1', 'parent_id': parent.pk, 'security_level': 3},
        ]


class RequirementStatusAPITest(APIViewTestCases.APIViewTestCase):
    model = RequirementStatus
    view_namespace = 'plugins-api:netbox_iec62443'
    graphql_base_name = 'iec62443_requirement_status'
    user_permissions = (
        'netbox_iec62443.view_zone', 'netbox_iec62443.view_conduit', 'netbox_iec62443.view_systemrequirement',
        'tenancy.view_contact',
    )
    brief_fields = ['description', 'display', 'id', 'status', 'url']
    bulk_update_data = {'status': 'not-applicable'}

    @classmethod
    def setUpTestData(cls):
        site = Site.objects.create(name='Site 1', slug='site-1')
        cell = Zone.objects.create(name='Cell', slug='cell', site=site)
        office = Zone.objects.create(name='Office', slug='office', site=site)
        conduit = Conduit.objects.create(name='Office - Cell', site=site)
        sr = [requirement(f'SR 1.{n}') for n in (1, 2, 3)]
        for s in sr:
            RequirementStatus.objects.create(zone=cell, requirement=s, status='met')
        cls.create_data = [
            {'zone': office.pk, 'requirement': sr[0].pk, 'status': 'met'},
            {'conduit': conduit.pk, 'requirement': sr[1].pk, 'status': 'compensated', 'countermeasure': 'Diode'},
            {'zone': office.pk, 'requirement': sr[2].pk, 'status': 'not-met', 'evidence': 'Shared passwords'},
        ]
