from django.urls import reverse
from rest_framework import status

from dcim.models import Site
from utilities.testing import APITestCase, APIViewTestCases, create_test_device

from netbox_iec62443.models import Conduit, Zone


class ZoneAPITest(APIViewTestCases.APIViewTestCase):
    model = Zone
    view_namespace = 'plugins-api:netbox_iec62443'
    graphql_base_name = 'iec62443_zone'
    brief_fields = ['description', 'display', 'id', 'name', 'purdue_level', 'slug', 'url']
    bulk_update_data = {
        'purdue_level': '3.5',
        'description': 'New description',
    }
    bulk_update_invalid_data = {
        'purdue_level': '7',
    }

    @classmethod
    def setUpTestData(cls):
        site = Site.objects.create(name='Site 1', slug='site-1')
        devices = [create_test_device(f'plc-{i}', site=site) for i in range(3)]
        Zone.objects.bulk_create([
            Zone(name='Zone 1', slug='zone-1', site=site, purdue_level='1'),
            Zone(name='Zone 2', slug='zone-2', site=site, purdue_level='2'),
            Zone(name='Zone 3', slug='zone-3', site=site, purdue_level='4'),
        ])
        cls.create_data = [
            {'name': 'Zone 4', 'slug': 'zone-4', 'site': site.pk, 'purdue_level': '1', 'security_level_target': 2,
             'devices': [devices[0].pk, devices[1].pk]},
            {'name': 'Zone 5', 'slug': 'zone-5', 'site': site.pk, 'purdue_level': '3.5'},
            {'name': 'Zone 6', 'slug': 'zone-6', 'purdue_level': '', 'devices': [devices[2].pk]},
        ]


class ConduitAPITest(APIViewTestCases.APIViewTestCase):
    model = Conduit
    view_namespace = 'plugins-api:netbox_iec62443'
    graphql_base_name = 'iec62443_conduit'
    user_permissions = ('netbox_iec62443.view_zone',)
    brief_fields = ['allowed', 'description', 'display', 'id', 'name', 'url']
    bulk_update_data = {
        'allowed': 'no',
        'remote_access': True,
        'via': '4G router of supplier X',
    }
    bulk_update_invalid_data = {
        'allowed': 'maybe',
    }

    @classmethod
    def setUpTestData(cls):
        site = Site.objects.create(name='Site 1', slug='site-1')
        office = Zone.objects.create(name='Office', slug='office', site=site, purdue_level='4')
        cell = Zone.objects.create(name='Cell', slug='cell', site=site, purdue_level='1')
        remote = Zone.objects.create(name='Remote', slug='remote', site=site)
        Conduit.objects.bulk_create([
            Conduit(name='Conduit 1', source_zone=office, destination_zone=cell),
            Conduit(name='Conduit 2', source_zone=remote, destination_zone=cell, remote_access=True),
            Conduit(name='Conduit 3', source_zone=cell, destination_zone=office, allowed='yes'),
        ])
        cls.create_data = [
            {'name': 'Conduit 4', 'source_zone': office.pk, 'destination_zone': cell.pk, 'allowed': 'no',
             'protocols': 'S7comm (TCP/102)'},
            {'name': 'Conduit 5', 'source_zone': remote.pk, 'destination_zone': cell.pk, 'remote_access': True,
             'via': 'TeamViewer on HMI', 'direction': 'two-way'},
            {'name': 'Conduit 6', 'source_zone': cell.pk, 'destination_zone': remote.pk, 'evidence': 'interview'},
        ]


class ConduitValidationAPITest(APITestCase):

    def test_same_zone_rejected(self):
        zone = Zone.objects.create(name='Cell', slug='cell')
        self.add_permissions('netbox_iec62443.add_conduit')
        url = reverse('plugins-api:netbox_iec62443-api:conduit-list')
        data = {'name': 'loop', 'source_zone': zone.pk, 'destination_zone': zone.pk}
        response = self.client.post(url, data, format='json', **self.header)
        self.assertHttpStatus(response, status.HTTP_400_BAD_REQUEST)
        self.assertIn('destination_zone', response.data)

    def test_purdue_level_accepts_number(self):
        self.add_permissions('netbox_iec62443.add_zone')
        url = reverse('plugins-api:netbox_iec62443-api:zone-list')
        response = self.client.post(url, {'name': 'Z', 'slug': 'z', 'purdue_level': 1}, format='json', **self.header)
        self.assertHttpStatus(response, status.HTTP_201_CREATED)
        self.assertEqual(Zone.objects.get(slug='z').purdue_level, '1')
