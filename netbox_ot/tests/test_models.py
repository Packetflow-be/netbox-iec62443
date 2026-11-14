import datetime

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase, override_settings
from django.utils import timezone

from dcim.models import Site
from extras.models import CustomField
from tenancy.models import Contact
from utilities.testing import create_test_device

from netbox_ot.accessmap import access_map_flows, access_map_svg, attention
from netbox_ot.choices import FlowAllowedChoices, PurdueLevelChoices, ZoneTypeChoices
from netbox_ot.customfields import PURDUE_CF_NAME
from netbox_ot.models import Conduit, Flow, FlowHop, Zone

TODAY = timezone.localdate()


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

    def test_str_color_and_type(self):
        zone = Zone(name='Cell A', slug='cell-a', purdue_level=PurdueLevelChoices.LEVEL_1)
        self.assertEqual(str(zone), 'Cell A')
        self.assertEqual(zone.get_purdue_level_color(), 'red')
        self.assertEqual(zone.zone_type, ZoneTypeChoices.OT)


class FlowTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(name='Site 1', slug='site-1')
        cls.office = Zone.objects.create(name='Office', slug='office', site=cls.site, purdue_level='4',
                                         zone_type='enterprise')
        cls.cell = Zone.objects.create(name='Cell', slug='cell', site=cls.site, purdue_level='1')
        cls.dmz = Zone.objects.create(name='DMZ', slug='dmz', site=cls.site, purdue_level='3.5', zone_type='dmz')
        cls.conduit = Conduit.objects.create(name='Office - Cell', site=cls.site)
        cls.conduit.zones.set([cls.office, cls.cell])
        cls.contact = Contact.objects.create(name='Plant manager')

    def test_same_zone_rejected(self):
        with self.assertRaises(ValidationError):
            Flow(source_zone=self.cell, destination_zone=self.cell).full_clean()

    def test_conduit_must_join_both_zones(self):
        Flow(source_zone=self.office, destination_zone=self.cell, conduit=self.conduit).full_clean()
        with self.assertRaisesRegex(ValidationError, 'does not join'):
            Flow(source_zone=self.dmz, destination_zone=self.cell, conduit=self.conduit).full_clean()

    def test_zones_of_two_sites(self):
        other = Site.objects.create(name='Site 2', slug='site-2')
        control = Zone.objects.create(name='Control room', slug='control-room', site=other, purdue_level='2')
        with self.assertRaisesRegex(ValidationError, 'This zone is at Site 2, the source zone at Site 1'):
            Flow(source_zone=self.cell, destination_zone=control).full_clean()
        # A central enterprise zone, a DMZ or an external zone may serve several sites; a zone without a site too
        hq = Zone.objects.create(name='HQ', slug='hq', site=other, zone_type='enterprise')
        Flow(source_zone=hq, destination_zone=self.cell).full_clean()
        Flow(source_zone=self.dmz, destination_zone=control).full_clean()
        siteless = Zone.objects.create(name='Vendor', slug='vendor', purdue_level='2')
        Flow(source_zone=siteless, destination_zone=control).full_clean()

    def test_long_port_list_is_shortened_for_lists(self):
        flow = Flow(source_zone=self.office, destination_zone=self.cell, port_mappings=['tcp/102', 'tcp/502'])
        self.assertEqual(flow.ports_short, 'TCP/102, TCP/502')
        flow.port_mappings = [f'tcp/{p}' for p in range(1, 59)]
        self.assertEqual(flow.ports_short, 'TCP/1, TCP/2, TCP/3, TCP/4, TCP/5, TCP/6, ... (58 ports)')
        self.assertEqual(flow.ports_display.count(','), 57)  # the flow page shows them all

    def test_port_mappings_validated_and_normalised(self):
        flow = Flow(source_zone=self.office, destination_zone=self.cell, port_mappings=['TCP/0102'])
        flow.full_clean()
        self.assertEqual(flow.port_mappings, ['tcp/102'])
        with self.assertRaises(ValidationError):
            Flow(source_zone=self.office, destination_zone=self.cell, port_mappings=['tcp/99999']).full_clean()

    def test_defaults_and_name(self):
        flow = Flow.objects.create(source_zone=self.office, destination_zone=self.cell, protocol='s7comm',
                                   access=['write', 'read', 'write'])
        self.assertEqual(flow.name, 'Office -> Cell S7comm')
        self.assertEqual(flow.allowed, FlowAllowedChoices.UNKNOWN)
        self.assertEqual(flow.access, ['read', 'write'])  # de-duplicated, in class order
        self.assertTrue(flow.is_modifying)
        self.assertIsNone(flow.decided_on)
        self.assertEqual(set(self.cell.flows), {flow})

    def test_verdict_is_dated_and_cleared(self):
        flow = Flow.objects.create(source_zone=self.office, destination_zone=self.cell, allowed='no',
                                   decided_by=self.contact)
        self.assertEqual(flow.decided_on, TODAY)  # dated when decided
        flow.allowed, flow.decided_on = 'yes', datetime.date(2026, 1, 5)
        flow.save()
        self.assertEqual(flow.decided_on, datetime.date(2026, 1, 5))  # a given date wins
        flow.allowed = 'no'
        flow.save()
        self.assertEqual(flow.decided_on, TODAY)  # verdict changed, date not: today
        flow.description = 'edited'
        flow.decided_on = datetime.date(2026, 2, 1)
        flow.save()
        self.assertEqual(flow.decided_on, datetime.date(2026, 2, 1))  # no verdict change: left alone
        flow.allowed = 'unknown'
        flow.save()
        self.assertEqual((flow.decided_on, flow.decided_by), (None, None))  # nobody decided "unknown"

    def test_expiry_review_and_stale(self):
        flow = Flow(source_zone=self.office, destination_zone=self.cell, allowed='yes',
                    expires=TODAY - datetime.timedelta(days=1), review_by=TODAY,
                    last_seen=timezone.now() - datetime.timedelta(days=200))
        self.assertTrue(flow.is_expired)
        self.assertTrue(flow.is_review_due)
        self.assertTrue(flow.is_stale)
        flow.allowed = 'no'
        self.assertFalse(flow.is_expired)  # only an allowed flow expires
        with override_settings(PLUGINS_CONFIG={'netbox_ot': {'stale_after_days': 365}}):
            self.assertFalse(flow.is_stale)

    def test_zone_with_flows_cannot_be_deleted(self):
        """Deleting a zone must not silently delete the verdicts and evidence on its flows."""
        Flow.objects.create(name='f', source_zone=self.office, destination_zone=self.cell, allowed='no',
                            evidence='seen')
        for zone in (self.office, self.cell):
            with self.assertRaises(ProtectedError), transaction.atomic():
                zone.delete()
        self.assertEqual(Flow.objects.get(name='f').allowed, 'no')
        self.dmz.delete()  # a zone without flows still deletes

    def test_deleting_a_conduit_keeps_its_flows(self):
        flow = Flow.objects.create(source_zone=self.office, destination_zone=self.cell, conduit=self.conduit,
                                   allowed='no')
        self.conduit.delete()
        flow.refresh_from_db()
        self.assertIsNone(flow.conduit)
        self.assertEqual(flow.allowed, 'no')

    def test_access_map(self):
        into_cell = Flow.objects.create(name='office to cell', source_zone=self.office, destination_zone=self.cell,
                                        allowed='yes')
        into_dmz = Flow.objects.create(name='office to dmz', source_zone=self.office, destination_zone=self.dmz)
        blocked = Flow.objects.create(name='dmz to cell', source_zone=self.dmz, destination_zone=self.cell,
                                      allowed='no')
        expired = Flow.objects.create(name='expired', source_zone=self.dmz, destination_zone=self.cell,
                                      allowed='yes', expires=TODAY - datetime.timedelta(days=1))
        unknown = Flow.objects.create(name='unknown', source_zone=self.office, destination_zone=self.cell,
                                      protocol='rdp', remote_access=True)
        result = list(access_map_flows(site=self.site, max_level='2'))
        # not allowed, expired, unknown, allowed; the DMZ (3.5) is above level 2
        self.assertEqual(result, [blocked, expired, unknown, into_cell])
        self.assertIn(into_dmz, access_map_flows(site=self.site, max_level='3.5'))
        other = Site.objects.create(name='Site 2', slug='site-2')
        self.assertEqual(list(access_map_flows(site=other)), [])
        svg = access_map_svg(result, Zone.objects.filter(site=self.site))
        self.assertIn('<svg', svg)
        self.assertIn('Office', svg)
        self.assertIn('stroke-dasharray', svg)  # the remote access pair is dashed
        counts = attention(Flow.objects.all())
        self.assertEqual((counts['expired'], counts['no_conduit']), (1, 5))


class FlowHopTest(TestCase):

    def test_exactly_one_target(self):
        site = Site.objects.create(name='Site 1', slug='site-1')
        a = Zone.objects.create(name='MSP', slug='msp', zone_type='external')
        b = Zone.objects.create(name='Cell', slug='cell', site=site, purdue_level='1')
        flow = Flow.objects.create(source_zone=a, destination_zone=b, protocol='rdp', remote_access=True)
        jump = create_test_device('jump-1', site=site)
        fw = create_test_device('fw-1', site=site)
        with self.assertRaises(ValidationError):
            FlowHop(flow=flow, position=1).full_clean()
        hops = [FlowHop(flow=flow, position=2, device=fw), FlowHop(flow=flow, position=1, device=jump)]
        for hop in hops:
            hop.full_clean()
            hop.save()
        self.assertEqual([str(h) for h in flow.hops.all()], ['1. jump-1', '2. fw-1'])
        with self.assertRaises(ValidationError):
            FlowHop(flow=flow, position=1, device=fw).full_clean()  # position taken


class CustomFieldTest(TestCase):

    def test_purdue_custom_field_created(self):
        cf = CustomField.objects.get(name=PURDUE_CF_NAME)
        self.assertEqual(cf.type, 'select')
        self.assertEqual(
            sorted(f'{ot.app_label}.{ot.model}' for ot in cf.object_types.all()),
            ['dcim.device', 'virtualization.virtualmachine'],
        )
        self.assertEqual([c[0] for c in cf.choice_set.choices], PurdueLevelChoices.values())
