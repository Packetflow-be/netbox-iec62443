from django.test import TestCase

from dcim.models import Site
from utilities.testing import ChangeLoggedFilterSetTestMixin, create_test_device

from netbox_iec62443.filtersets import ConduitFilterSet, ZoneFilterSet
from netbox_iec62443.models import Conduit, Zone


class ZoneFilterSetTest(TestCase, ChangeLoggedFilterSetTestMixin):
    queryset = Zone.objects.all()
    filterset = ZoneFilterSet
    ignore_fields = ('devices', 'virtual_machines', 'prefixes')

    @classmethod
    def setUpTestData(cls):
        cls.sites = (Site.objects.create(name='Site 1', slug='site-1'), Site.objects.create(name='Site 2', slug='site-2'))
        cls.device = create_test_device('plc-1', site=cls.sites[0])
        zones = (
            Zone.objects.create(name='Zone 1', slug='zone-1', site=cls.sites[0], purdue_level='1',
                                security_level_target=2, description='foobar1'),
            Zone.objects.create(name='Zone 2', slug='zone-2', site=cls.sites[0], purdue_level='3.5'),
            Zone.objects.create(name='Zone 3', slug='zone-3', site=cls.sites[1], purdue_level='4'),
        )
        zones[0].devices.add(cls.device)

    def test_q(self):
        self.assertEqual(self.filterset({'q': 'foobar1'}, self.queryset).qs.count(), 1)

    def test_name(self):
        self.assertEqual(self.filterset({'name': ['Zone 1', 'Zone 2']}, self.queryset).qs.count(), 2)

    def test_site(self):
        self.assertEqual(self.filterset({'site_id': [self.sites[0].pk]}, self.queryset).qs.count(), 2)
        self.assertEqual(self.filterset({'site': ['site-2']}, self.queryset).qs.count(), 1)

    def test_purdue_level(self):
        self.assertEqual(self.filterset({'purdue_level': ['1', '3.5']}, self.queryset).qs.count(), 2)

    def test_security_level_target(self):
        self.assertEqual(self.filterset({'security_level_target': [2]}, self.queryset).qs.count(), 1)

    def test_device(self):
        self.assertEqual(self.filterset({'device_id': [self.device.pk]}, self.queryset).qs.count(), 1)


class ConduitFilterSetTest(TestCase, ChangeLoggedFilterSetTestMixin):
    queryset = Conduit.objects.all()
    filterset = ConduitFilterSet
    ignore_fields = ('evidence',)

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(name='Site 1', slug='site-1')
        other = Site.objects.create(name='Site 2', slug='site-2')
        cls.zones = (
            Zone.objects.create(name='Office', slug='office', site=cls.site, purdue_level='4'),
            Zone.objects.create(name='Cell', slug='cell', site=cls.site, purdue_level='1'),
            Zone.objects.create(name='Remote', slug='remote', site=other),
        )
        Conduit.objects.create(name='Conduit 1', source_zone=cls.zones[0], destination_zone=cls.zones[1],
                               allowed='no', protocols='S7comm')
        Conduit.objects.create(name='Conduit 2', source_zone=cls.zones[2], destination_zone=cls.zones[1],
                               remote_access=True, via='4G router')
        Conduit.objects.create(name='Conduit 3', source_zone=cls.zones[1], destination_zone=cls.zones[0],
                               allowed='yes', direction='two-way')

    def test_q(self):
        self.assertEqual(self.filterset({'q': '4G'}, self.queryset).qs.count(), 1)

    def test_name(self):
        self.assertEqual(self.filterset({'name': ['Conduit 1']}, self.queryset).qs.count(), 1)

    def test_zones(self):
        self.assertEqual(self.filterset({'source_zone_id': [self.zones[0].pk]}, self.queryset).qs.count(), 1)
        self.assertEqual(self.filterset({'destination_zone_id': [self.zones[1].pk]}, self.queryset).qs.count(), 2)
        self.assertEqual(self.filterset({'zone_id': [self.zones[0].pk]}, self.queryset).qs.count(), 2)

    def test_site(self):
        self.assertEqual(self.filterset({'site_id': [self.site.pk]}, self.queryset).qs.count(), 3)

    def test_allowed(self):
        self.assertEqual(self.filterset({'allowed': ['no', 'yes']}, self.queryset).qs.count(), 2)

    def test_direction(self):
        self.assertEqual(self.filterset({'direction': ['two-way']}, self.queryset).qs.count(), 1)

    def test_remote_access(self):
        self.assertEqual(self.filterset({'remote_access': True}, self.queryset).qs.count(), 1)
