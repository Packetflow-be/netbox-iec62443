import datetime

from django.test import TestCase
from django.utils import timezone

from dcim.models import Site
from tenancy.models import Contact
from utilities.testing import ChangeLoggedFilterSetTestMixin, create_test_device

from netbox_ot.filtersets import (
    ConduitFilterSet,
    FlowFilterSet,
    FlowHopFilterSet,
    RiskAssessmentFilterSet,
    ZoneFilterSet,
)
from netbox_ot.models import Conduit, Flow, FlowHop, RiskAssessment, Zone

TODAY = timezone.localdate()


class ZoneFilterSetTest(TestCase, ChangeLoggedFilterSetTestMixin):
    queryset = Zone.objects.all()
    filterset = ZoneFilterSet
    ignore_fields = ('devices', 'virtual_machines', 'prefixes', 'sl_target', 'sl_achieved')

    @classmethod
    def setUpTestData(cls):
        cls.sites = (
            Site.objects.create(name='Site 1', slug='site-1'),
            Site.objects.create(name='Site 2', slug='site-2'),
        )
        cls.device = create_test_device('plc-1', site=cls.sites[0])
        zones = (
            Zone.objects.create(name='Zone 1', slug='zone-1', site=cls.sites[0], purdue_level='1',
                                sl_target=[2] * 7, sl_achieved=[2, 2, 1, 2, 2, 2, 2], description='foobar1',
                                wireless=True),
            Zone.objects.create(name='Zone 2', slug='zone-2', site=cls.sites[0], purdue_level='3.5', zone_type='dmz'),
            Zone.objects.create(name='Zone 3', slug='zone-3', site=cls.sites[1], purdue_level='4',
                                zone_type='enterprise'),
        )
        zones[0].devices.add(cls.device)
        cls.conduit = Conduit.objects.create(name='C1')
        cls.conduit.zones.set(zones[:2])

    def test_q(self):
        self.assertEqual(self.filterset({'q': 'foobar1'}, self.queryset).qs.count(), 1)

    def test_name(self):
        self.assertEqual(self.filterset({'name': ['Zone 1', 'Zone 2']}, self.queryset).qs.count(), 2)

    def test_site(self):
        self.assertEqual(self.filterset({'site_id': [self.sites[0].pk]}, self.queryset).qs.count(), 2)
        self.assertEqual(self.filterset({'site': ['site-2']}, self.queryset).qs.count(), 1)

    def test_zone_type_and_level(self):
        self.assertEqual(self.filterset({'zone_type': ['dmz', 'enterprise']}, self.queryset).qs.count(), 2)
        self.assertEqual(self.filterset({'purdue_level': ['1', '3.5']}, self.queryset).qs.count(), 2)

    def test_security_levels_and_attributes(self):
        self.assertEqual(self.filterset({'has_sl_target': True}, self.queryset).qs.count(), 1)
        self.assertEqual(self.filterset({'sl_gap': True}, self.queryset).qs.count(), 1)
        self.assertEqual(self.filterset({'sl_gap': False}, self.queryset).qs.count(), 2)
        self.assertEqual(self.filterset({'wireless': True}, self.queryset).qs.count(), 1)

    def test_device_and_conduit(self):
        self.assertEqual(self.filterset({'device_id': [self.device.pk]}, self.queryset).qs.count(), 1)
        self.assertEqual(self.filterset({'conduit_id': [self.conduit.pk]}, self.queryset).qs.count(), 2)


class ConduitFilterSetTest(TestCase, ChangeLoggedFilterSetTestMixin):
    queryset = Conduit.objects.all()
    filterset = ConduitFilterSet
    ignore_fields = ('zones', 'enforcing_devices', 'enforcing_virtual_machines', 'sl_target', 'sl_achieved')

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(name='Site 1', slug='site-1')
        cls.zones = [Zone.objects.create(name=f'Z{i}', slug=f'z{i}', site=cls.site) for i in range(3)]
        cls.fw = create_test_device('fw-1', site=cls.site)
        c1 = Conduit.objects.create(name='C1', site=cls.site, sl_target=[2] * 7, description='diode')
        c1.zones.set(cls.zones[:2])
        c1.enforcing_devices.add(cls.fw)
        Conduit.objects.create(name='C2', site=cls.site).zones.set(cls.zones[1:])
        Conduit.objects.create(name='C3').zones.set([cls.zones[0], cls.zones[2]])

    def test_q(self):
        self.assertEqual(self.filterset({'q': 'diode'}, self.queryset).qs.count(), 1)

    def test_site_zone(self):
        self.assertEqual(self.filterset({'site_id': [self.site.pk]}, self.queryset).qs.count(), 2)
        self.assertEqual(self.filterset({'zone_id': [self.zones[0].pk]}, self.queryset).qs.count(), 2)

    def test_sl_and_enforcing(self):
        self.assertEqual(self.filterset({'has_sl_target': True}, self.queryset).qs.count(), 1)
        self.assertEqual(self.filterset({'enforcing_device_id': [self.fw.pk]}, self.queryset).qs.count(), 1)


class FlowFilterSetTest(TestCase, ChangeLoggedFilterSetTestMixin):
    queryset = Flow.objects.all()
    filterset = FlowFilterSet
    ignore_fields = ('evidence', 'port_mappings', 'access')

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(name='Site 1', slug='site-1')
        other = Site.objects.create(name='Site 2', slug='site-2')
        cls.zones = (
            Zone.objects.create(name='Office', slug='office', site=cls.site, purdue_level='4'),
            Zone.objects.create(name='Cell', slug='cell', site=cls.site, purdue_level='1'),
            Zone.objects.create(name='Remote', slug='remote', site=other, zone_type='external'),
        )
        cls.conduit = Conduit.objects.create(name='Office - Cell', site=cls.site)
        cls.conduit.zones.set(cls.zones[:2])
        cls.contact = Contact.objects.create(name='Plant manager')
        cls.fw = create_test_device('fw-1', site=cls.site)
        Flow.objects.create(name='Flow 1', source_zone=cls.zones[0], destination_zone=cls.zones[1], allowed='no',
                            conduit=cls.conduit, protocol='s7comm', port_mappings=['tcp/102'],
                            access=['read', 'write'], decided_by=cls.contact)
        f2 = Flow.objects.create(name='Flow 2', source_zone=cls.zones[2], destination_zone=cls.zones[1],
                                 remote_access=True, protocol='rdp', port_mappings=['tcp/3389'],
                                 last_seen=timezone.now() - datetime.timedelta(days=400))
        FlowHop.objects.create(flow=f2, position=1, device=cls.fw)
        Flow.objects.create(name='Flow 3', source_zone=cls.zones[1], destination_zone=cls.zones[0], allowed='yes',
                            access=['read'], expires=TODAY - datetime.timedelta(days=1), review_by=TODAY,
                            description='historian')

    def _count(self, params):
        return self.filterset(params, self.queryset).qs.count()

    def test_q(self):
        self.assertEqual(self._count({'q': 'historian'}), 1)

    def test_zones_site_conduit(self):
        self.assertEqual(self._count({'source_zone_id': [self.zones[0].pk]}), 1)
        self.assertEqual(self._count({'destination_zone_id': [self.zones[1].pk]}), 2)
        self.assertEqual(self._count({'zone_id': [self.zones[0].pk]}), 2)
        self.assertEqual(self._count({'site_id': [self.site.pk]}), 3)
        self.assertEqual(self._count({'conduit_id': [self.conduit.pk]}), 1)
        self.assertEqual(self._count({'has_conduit': False}), 2)

    def test_protocol_port_access(self):
        self.assertEqual(self._count({'protocol': ['s7comm', 'rdp']}), 2)
        self.assertEqual(self._count({'port': 102}), 1)
        self.assertEqual(self._count({'access': ['write']}), 1)
        self.assertEqual(self._count({'modifying': True}), 1)
        self.assertEqual(self._count({'modifying': False}), 2)

    def test_verdict(self):
        self.assertEqual(self._count({'allowed': ['no', 'yes']}), 2)
        self.assertEqual(self._count({'remote_access': True}), 1)
        self.assertEqual(self._count({'decided_by_id': [self.contact.pk]}), 1)
        self.assertEqual(self._count({'expired': True}), 1)
        self.assertEqual(self._count({'review_due': True}), 1)
        self.assertEqual(self._count({'stale': True}), 1)

    def test_hops(self):
        self.assertEqual(self._count({'hop_device_id': [self.fw.pk]}), 1)


class FlowHopFilterSetTest(TestCase, ChangeLoggedFilterSetTestMixin):
    queryset = FlowHop.objects.all()
    filterset = FlowHopFilterSet

    @classmethod
    def setUpTestData(cls):
        site = Site.objects.create(name='Site 1', slug='site-1')
        a = Zone.objects.create(name='MSP', slug='msp', zone_type='external')
        b = Zone.objects.create(name='Cell', slug='cell', site=site)
        cls.flow = Flow.objects.create(source_zone=a, destination_zone=b, protocol='rdp')
        cls.jump = create_test_device('jump-1', site=site)
        FlowHop.objects.create(flow=cls.flow, position=1, device=cls.jump, description='jump host')
        FlowHop.objects.create(flow=cls.flow, position=2, device=create_test_device('fw-1', site=site))
        FlowHop.objects.create(flow=cls.flow, position=3, device=create_test_device('plc-1', site=site))

    def test_flow_device_q(self):
        self.assertEqual(self.filterset({'flow_id': [self.flow.pk]}, self.queryset).qs.count(), 3)
        self.assertEqual(self.filterset({'device_id': [self.jump.pk]}, self.queryset).qs.count(), 1)
        self.assertEqual(self.filterset({'q': 'jump'}, self.queryset).qs.count(), 1)



class RiskAssessmentFilterSetTest(TestCase, ChangeLoggedFilterSetTestMixin):
    queryset = RiskAssessment.objects.all()
    filterset = RiskAssessmentFilterSet
    ignore_fields = ('threats', 'vulnerabilities', 'consequences', 'countermeasures', 'document')

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(name='Site 1', slug='site-1')
        cls.zone = Zone.objects.create(name='Cell', slug='cell', site=cls.site)
        other = Zone.objects.create(name='Office', slug='office', site=cls.site)
        cls.conduit = Conduit.objects.create(name='C1')
        cls.conduit.zones.set([cls.zone, other])
        RiskAssessment.objects.create(zone=cls.zone, assessed_on=TODAY, residual_risk='high', tolerable_risk='medium',
                                      next_review=TODAY, method='company matrix')
        RiskAssessment.objects.create(zone=other, assessed_on=TODAY, kind='initial', residual_risk='low',
                                      tolerable_risk='medium')
        RiskAssessment.objects.create(conduit=cls.conduit, assessed_on=TODAY, status='approved', approved_on=TODAY)

    def _count(self, params):
        return self.filterset(params, self.queryset).qs.count()

    def test_subject_and_site(self):
        self.assertEqual(self._count({'zone_id': [self.zone.pk]}), 1)
        self.assertEqual(self._count({'conduit_id': [self.conduit.pk]}), 1)
        self.assertEqual(self._count({'site_id': [self.site.pk]}), 3)

    def test_kind_status_risk(self):
        self.assertEqual(self._count({'kind': ['initial']}), 1)
        self.assertEqual(self._count({'status': ['approved']}), 1)
        self.assertEqual(self._count({'residual_above_tolerable': True}), 1)
        self.assertEqual(self._count({'review_due': True}), 1)
        self.assertEqual(self._count({'q': 'matrix'}), 1)
