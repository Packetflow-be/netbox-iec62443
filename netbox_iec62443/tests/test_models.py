from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from dcim.models import Site
from extras.models import CustomField

from netbox_iec62443.accessmap import access_map_conduits, access_map_svg
from netbox_iec62443.choices import ConduitAllowedChoices, ConduitDirectionChoices, PurdueLevelChoices
from netbox_iec62443.customfields import PURDUE_CF_NAME
from netbox_iec62443.models import Conduit, Zone


class PurdueLevelChoicesTest(TestCase):

    def test_at_or_below(self):
        self.assertEqual(PurdueLevelChoices.at_or_below('2'), ['0', '1', '2'])
        self.assertEqual(PurdueLevelChoices.at_or_below('3.5'), ['0', '1', '2', '3', '3.5'])
        self.assertEqual(PurdueLevelChoices.at_or_below('0'), ['0'])


class ZoneTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.site1 = Site.objects.create(name='Site 1', slug='site-1')
        cls.site2 = Site.objects.create(name='Site 2', slug='site-2')

    def test_name_unique_per_site(self):
        Zone.objects.create(name='Machines', slug='machines', site=self.site1)
        Zone(name='Machines', slug='machines', site=self.site2).full_clean()  # other site: fine
        with self.assertRaises(ValidationError):
            Zone(name='Machines', slug='machines-2', site=self.site1).full_clean()

    def test_name_unique_without_site(self):
        Zone.objects.create(name='Internet', slug='internet')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Zone.objects.create(name='Internet', slug='internet-2')

    def test_str_and_color(self):
        zone = Zone(name='Cell A', slug='cell-a', purdue_level=PurdueLevelChoices.LEVEL_1)
        self.assertEqual(str(zone), 'Cell A')
        self.assertEqual(zone.get_purdue_level_color(), 'red')


class ConduitTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(name='Site 1', slug='site-1')
        cls.office = Zone.objects.create(name='Office', slug='office', site=cls.site, purdue_level='4')
        cls.cell = Zone.objects.create(name='Cell', slug='cell', site=cls.site, purdue_level='1')
        cls.dmz = Zone.objects.create(name='DMZ', slug='dmz', site=cls.site, purdue_level='3.5')

    def test_same_zone_rejected(self):
        with self.assertRaises(ValidationError):
            Conduit(name='loop', source_zone=self.cell, destination_zone=self.cell).full_clean()

    def test_zone_with_conduits_cannot_be_deleted(self):
        """Deleting a zone must not silently delete the verdicts and evidence on its conduits."""
        Conduit.objects.create(name='c', source_zone=self.office, destination_zone=self.cell, allowed='no',
                               evidence='seen')
        for zone in (self.office, self.cell):
            with self.assertRaises(ProtectedError), transaction.atomic():
                zone.delete()
        self.assertEqual(Conduit.objects.get(name='c').allowed, 'no')
        self.dmz.delete()  # a zone without conduits still deletes

    def test_defaults(self):
        c = Conduit.objects.create(name='c', source_zone=self.office, destination_zone=self.cell)
        self.assertEqual(c.allowed, ConduitAllowedChoices.UNKNOWN)
        self.assertEqual(c.direction, ConduitDirectionChoices.ONE_WAY)
        self.assertFalse(c.remote_access)
        self.assertEqual(set(self.cell.conduits), {c})

    def test_access_map(self):
        into_cell = Conduit.objects.create(name='office to cell', source_zone=self.office, destination_zone=self.cell,
                                           allowed='yes')
        into_dmz = Conduit.objects.create(name='office to dmz', source_zone=self.office, destination_zone=self.dmz)
        two_way = Conduit.objects.create(name='cell and dmz', source_zone=self.cell, destination_zone=self.dmz,
                                         direction='two-way', allowed='no')
        result = list(access_map_conduits(site=self.site, max_level='2'))
        # "no" before "yes"; the two-way conduit counts from its level-1 end; DMZ (3.5) is above 2
        self.assertEqual(result, [two_way, into_cell])
        self.assertIn(into_dmz, access_map_conduits(site=self.site, max_level='3.5'))
        other = Site.objects.create(name='Site 2', slug='site-2')
        self.assertEqual(list(access_map_conduits(site=other)), [])
        svg = access_map_svg(result, Zone.objects.filter(site=self.site))
        self.assertIn('<svg', svg)
        self.assertIn('Office', svg)


class CustomFieldTest(TestCase):

    def test_purdue_custom_field_created(self):
        cf = CustomField.objects.get(name=PURDUE_CF_NAME)
        self.assertEqual(cf.type, 'select')
        self.assertEqual(
            sorted(f'{ot.app_label}.{ot.model}' for ot in cf.object_types.all()),
            ['dcim.device', 'virtualization.virtualmachine'],
        )
        self.assertEqual([c[0] for c in cf.choice_set.choices], PurdueLevelChoices.values())
