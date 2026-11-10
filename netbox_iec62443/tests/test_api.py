from django.urls import reverse
from rest_framework import status

from dcim.models import Site
from tenancy.models import Contact
from utilities.testing import APITestCase, APIViewTestCases, create_test_device

from netbox_iec62443.models import Conduit, Flow, FlowHop, Zone


class ZoneAPITest(APIViewTestCases.APIViewTestCase):
    model = Zone
    view_namespace = 'plugins-api:netbox_iec62443'
    graphql_base_name = 'iec62443_zone'
    brief_fields = ['description', 'display', 'id', 'name', 'purdue_level', 'slug', 'url', 'zone_type']
    bulk_update_data = {
        'purdue_level': '3.5',
        'zone_type': 'dmz',
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
            {'name': 'Zone 5', 'slug': 'zone-5', 'site': site.pk, 'purdue_level': '3.5', 'zone_type': 'dmz'},
            {'name': 'Zone 6', 'slug': 'zone-6', 'purdue_level': '', 'zone_type': 'external',
             'devices': [devices[2].pk]},
        ]


class ConduitAPITest(APIViewTestCases.APIViewTestCase):
    model = Conduit
    view_namespace = 'plugins-api:netbox_iec62443'
    graphql_base_name = 'iec62443_conduit'
    user_permissions = ('netbox_iec62443.view_zone', 'dcim.view_device')
    brief_fields = ['description', 'display', 'id', 'name', 'url']
    bulk_update_data = {
        'security_level_target': 3,
    }
    bulk_update_invalid_data = {
        'security_level_target': 9,
    }

    @classmethod
    def setUpTestData(cls):
        site = Site.objects.create(name='Site 1', slug='site-1')
        office = Zone.objects.create(name='Office', slug='office', site=site, purdue_level='4')
        cell = Zone.objects.create(name='Cell', slug='cell', site=site, purdue_level='1')
        dmz = Zone.objects.create(name='DMZ', slug='dmz', site=site, purdue_level='3.5')
        fw = create_test_device('fw-1', site=site)
        for name in ('Conduit 1', 'Conduit 2', 'Conduit 3'):
            Conduit.objects.create(name=name, site=site).zones.set([office, cell])
        cls.create_data = [
            {'name': 'Conduit 4', 'site': site.pk, 'zones': [office.pk, dmz.pk], 'security_level_target': 2,
             'enforcing_devices': [fw.pk]},
            {'name': 'Conduit 5', 'site': site.pk, 'zones': [cell.pk, dmz.pk]},
            {'name': 'Conduit 6', 'zones': sorted([office.pk, dmz.pk, cell.pk])},
        ]


class FlowAPITest(APIViewTestCases.APIViewTestCase):
    model = Flow
    view_namespace = 'plugins-api:netbox_iec62443'
    graphql_base_name = 'iec62443_flow'
    user_permissions = ('netbox_iec62443.view_zone', 'netbox_iec62443.view_conduit', 'tenancy.view_contact')
    brief_fields = ['allowed', 'description', 'display', 'id', 'name', 'url']
    bulk_update_data = {
        'allowed': 'no',
        'remote_access': True,
        'access': ['write'],
    }
    bulk_update_invalid_data = {
        'allowed': 'maybe',
    }

    @classmethod
    def setUpTestData(cls):
        site = Site.objects.create(name='Site 1', slug='site-1')
        office = Zone.objects.create(name='Office', slug='office', site=site, purdue_level='4')
        cell = Zone.objects.create(name='Cell', slug='cell', site=site, purdue_level='1')
        remote = Zone.objects.create(name='Remote', slug='remote', site=site, zone_type='external')
        conduit = Conduit.objects.create(name='Remote - Cell', site=site)
        conduit.zones.set([remote, cell])
        contact = Contact.objects.create(name='Plant manager')
        Flow.objects.bulk_create([
            Flow(name='Flow 1', source_zone=office, destination_zone=cell),
            Flow(name='Flow 2', source_zone=remote, destination_zone=cell, remote_access=True),
            Flow(name='Flow 3', source_zone=cell, destination_zone=office, allowed='yes'),
        ])
        cls.create_data = [
            {'name': 'Flow 4', 'source_zone': office.pk, 'destination_zone': cell.pk, 'allowed': 'no',
             'protocol': 's7comm', 'port_mappings': ['tcp/102'], 'access': ['read', 'write'],
             'decided_by': contact.pk},
            {'name': 'Flow 5', 'source_zone': remote.pk, 'destination_zone': cell.pk, 'remote_access': True,
             'conduit': conduit.pk, 'protocol': 'rdp', 'expires': '2027-01-31'},
            {'name': 'Flow 6', 'source_zone': cell.pk, 'destination_zone': remote.pk, 'evidence': 'interview'},
        ]


class FlowHopAPITest(APIViewTestCases.APIViewTestCase):
    model = FlowHop
    view_namespace = 'plugins-api:netbox_iec62443'
    graphql_base_name = 'iec62443_flow_hop'
    user_permissions = ('netbox_iec62443.view_flow', 'dcim.view_device')
    brief_fields = ['description', 'display', 'id', 'position', 'url']
    bulk_update_data = {
        'description': 'jump host',
    }
    bulk_update_invalid_data = {
        'position': -1,
    }

    @classmethod
    def setUpTestData(cls):
        site = Site.objects.create(name='Site 1', slug='site-1')
        msp = Zone.objects.create(name='MSP', slug='msp', zone_type='external')
        cell = Zone.objects.create(name='Cell', slug='cell', site=site, purdue_level='1')
        flow = Flow.objects.create(name='MSP RDP', source_zone=msp, destination_zone=cell, protocol='rdp')
        devices = [create_test_device(f'hop-{i}', site=site) for i in range(6)]
        for i in range(3):
            FlowHop.objects.create(flow=flow, position=i + 1, device=devices[i])
        cls.create_data = [
            {'flow': flow.pk, 'position': 4, 'device': devices[3].pk},
            {'flow': flow.pk, 'position': 5, 'device': devices[4].pk},
            {'flow': flow.pk, 'position': 6, 'device': devices[5].pk},
        ]


class ValidationAPITest(APITestCase):

    def setUp(self):
        super().setUp()
        self.office = Zone.objects.create(name='Office', slug='office', purdue_level='4')
        self.cell = Zone.objects.create(name='Cell', slug='cell', purdue_level='1')
        self.dmz = Zone.objects.create(name='DMZ', slug='dmz', purdue_level='3.5')

    def test_flow_same_zone_rejected(self):
        self.add_permissions('netbox_iec62443.add_flow')
        url = reverse('plugins-api:netbox_iec62443-api:flow-list')
        data = {'name': 'loop', 'source_zone': self.cell.pk, 'destination_zone': self.cell.pk}
        response = self.client.post(url, data, format='json', **self.header)
        self.assertHttpStatus(response, status.HTTP_400_BAD_REQUEST)
        self.assertIn('destination_zone', response.data)

    def test_conduit_needs_two_zones(self):
        self.add_permissions('netbox_iec62443.add_conduit')
        url = reverse('plugins-api:netbox_iec62443-api:conduit-list')
        response = self.client.post(url, {'name': 'C', 'zones': [self.cell.pk]}, format='json', **self.header)
        self.assertHttpStatus(response, status.HTTP_400_BAD_REQUEST)

    def test_flow_conduit_must_join_its_zones(self):
        self.add_permissions('netbox_iec62443.add_flow')
        conduit = Conduit.objects.create(name='Office - DMZ')
        conduit.zones.set([self.office, self.dmz])
        url = reverse('plugins-api:netbox_iec62443-api:flow-list')
        data = {'source_zone': self.office.pk, 'destination_zone': self.cell.pk, 'conduit': conduit.pk}
        response = self.client.post(url, data, format='json', **self.header)
        self.assertHttpStatus(response, status.HTTP_400_BAD_REQUEST)

    def test_purdue_level_accepts_number(self):
        self.add_permissions('netbox_iec62443.add_zone')
        url = reverse('plugins-api:netbox_iec62443-api:zone-list')
        response = self.client.post(url, {'name': 'Z', 'slug': 'z', 'purdue_level': 1}, format='json', **self.header)
        self.assertHttpStatus(response, status.HTTP_201_CREATED)
        self.assertEqual(Zone.objects.get(slug='z').purdue_level, '1')


class AccessMapAPITest(APITestCase):

    def setUp(self):
        super().setUp()
        self.site = Site.objects.create(name='Site 1', slug='site-1')
        office = Zone.objects.create(name='Office', slug='office', site=self.site, purdue_level='4')
        cell = Zone.objects.create(name='Cell', slug='cell', site=self.site, purdue_level='1')
        flow = Flow.objects.create(name='office to cell', source_zone=office, destination_zone=cell, allowed='no',
                                   protocol='s7comm', port_mappings=['tcp/102'])
        FlowHop.objects.create(flow=flow, position=1, device=create_test_device('fw-1', site=self.site))
        Flow.objects.create(name='cell to office', source_zone=cell, destination_zone=office, allowed='yes')
        self.url = reverse('plugins-api:netbox_iec62443-api:accessmap')

    def test_access_map(self):
        self.add_permissions('netbox_iec62443.view_flow', 'netbox_iec62443.view_zone', 'dcim.view_site')
        response = self.client.get(f'{self.url}?site_id={self.site.pk}', **self.header)
        self.assertHttpStatus(response, status.HTTP_200_OK)
        self.assertEqual([f['name'] for f in response.data['flows']], ['office to cell'])
        flow = response.data['flows'][0]
        self.assertEqual(flow['allowed']['value'], 'no')
        self.assertEqual(flow['port_mappings'], ['tcp/102'])
        self.assertEqual([(h['position'], h['kind'], h['name']) for h in flow['hops']], [(1, 'device', 'fw-1')])
        self.assertNotIn('svg', response.data)  # cut: the diagram belongs to the UI
        response = self.client.get(f'{self.url}?site_id={self.site.pk}&max_level=4', **self.header)
        self.assertEqual(len(response.data['flows']), 2)

    def test_access_map_needs_permission_and_site(self):
        response = self.client.get(f'{self.url}?site_id={self.site.pk}', **self.header)
        self.assertHttpStatus(response, status.HTTP_403_FORBIDDEN)
        self.add_permissions('netbox_iec62443.view_flow', 'dcim.view_site')
        response = self.client.get(self.url, **self.header)
        self.assertHttpStatus(response, status.HTTP_400_BAD_REQUEST)
        response = self.client.get(f'{self.url}?site_id={self.site.pk}&max_level=9', **self.header)
        self.assertHttpStatus(response, status.HTTP_400_BAD_REQUEST)
