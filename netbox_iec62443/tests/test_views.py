from django.test import override_settings
from django.urls import reverse

from dcim.models import Site
from utilities.testing import TestCase, ViewTestCases, create_tags, create_test_device

from netbox_iec62443.models import Conduit, Zone


class PluginURLMixin:
    def _get_base_url(self):
        return f'plugins:netbox_iec62443:{self.model._meta.model_name}_{{}}'


class ZoneViewTest(PluginURLMixin, ViewTestCases.PrimaryObjectViewTestCase):
    model = Zone

    @classmethod
    def setUpTestData(cls):
        site = Site.objects.create(name='Site 1', slug='site-1')
        device = create_test_device('plc-1', site=site)
        Zone.objects.bulk_create([
            Zone(name='Zone 1', slug='zone-1', site=site, purdue_level='1'),
            Zone(name='Zone 2', slug='zone-2', site=site, purdue_level='2'),
            Zone(name='Zone 3', slug='zone-3', site=site, purdue_level='3'),
        ])
        tags = create_tags('Alpha', 'Bravo', 'Charlie')
        cls.form_data = {
            'name': 'Zone X',
            'slug': 'zone-x',
            'site': site.pk,
            'purdue_level': '1',
            'security_level_target': 2,
            'devices': [device.pk],
            'description': 'Controllers of line 1',
            'tags': [t.pk for t in tags],
        }
        cls.csv_data = (
            'name,slug,site,purdue_level,security_level_target',
            'Zone 4,zone-4,Site 1,0,1',
            'Zone 5,zone-5,Site 1,3.5,',
            'Zone 6,zone-6,,5,',
        )
        cls.csv_update_data = (
            'id,purdue_level,description',
            f'{Zone.objects.get(slug="zone-1").pk},2,changed',
            f'{Zone.objects.get(slug="zone-2").pk},3,changed',
            f'{Zone.objects.get(slug="zone-3").pk},4,changed',
        )
        cls.bulk_edit_data = {
            'purdue_level': '3.5',
            'security_level_target': 3,
        }


class ConduitViewTest(PluginURLMixin, ViewTestCases.PrimaryObjectViewTestCase):
    model = Conduit

    @classmethod
    def setUpTestData(cls):
        site = Site.objects.create(name='Site 1', slug='site-1')
        office = Zone.objects.create(name='Office', slug='office', site=site, purdue_level='4')
        cell = Zone.objects.create(name='Cell', slug='cell', site=site, purdue_level='1')
        remote = Zone.objects.create(name='Remote', slug='remote', site=site)
        Conduit.objects.bulk_create([
            Conduit(name='Conduit 1', source_zone=office, destination_zone=cell),
            Conduit(name='Conduit 2', source_zone=remote, destination_zone=cell),
            Conduit(name='Conduit 3', source_zone=cell, destination_zone=office),
        ])
        tags = create_tags('Alpha', 'Bravo', 'Charlie')
        cls.form_data = {
            'name': 'Conduit X',
            'source_zone': remote.pk,
            'destination_zone': cell.pk,
            'direction': 'one-way',
            'allowed': 'no',
            'protocols': 'S7comm (TCP/102) write',
            'remote_access': True,
            'via': '4G router of supplier X',
            'evidence': 'Seen in capture 1',
            'tags': [t.pk for t in tags],
        }
        cls.csv_data = (
            'site,name,source_zone,destination_zone,allowed,remote_access,via',
            'Site 1,Conduit 4,Office,Cell,no,false,',
            'Site 1,Conduit 5,Remote,Cell,unknown,true,TeamViewer',
            'Site 1,Conduit 6,Cell,Remote,yes,false,',
        )
        cls.csv_update_data = (
            'id,allowed,via',
            f'{Conduit.objects.get(name="Conduit 1").pk},yes,firewall',
            f'{Conduit.objects.get(name="Conduit 2").pk},no,4G router',
            f'{Conduit.objects.get(name="Conduit 3").pk},unknown,',
        )
        cls.bulk_edit_data = {
            'allowed': 'no',
            'direction': 'two-way',
        }


class AccessMapViewTest(TestCase):
    user_permissions = ('netbox_iec62443.view_conduit', 'netbox_iec62443.view_zone', 'dcim.view_site',
                        'dcim.view_device')

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(name='Site 1', slug='site-1')
        office = Zone.objects.create(name='Office', slug='office', site=cls.site, purdue_level='4')
        cell = Zone.objects.create(name='Cell A', slug='cell-a', site=cls.site, purdue_level='1')
        Conduit.objects.create(name='office to cell', source_zone=office, destination_zone=cell, allowed='no',
                               via='flat network', evidence='96243 connections')
        cls.device = create_test_device('plc-1', site=cls.site)
        cell.devices.add(cls.device)

    @override_settings(EXEMPT_VIEW_PERMISSIONS=[])
    def test_access_map_page(self):
        response = self.client.get(reverse('plugins:netbox_iec62443:accessmap') + f'?site_id={self.site.pk}')
        self.assertHttpStatus(response, 200)
        self.assertContains(response, 'office to cell')
        self.assertContains(response, 'flat network')
        self.assertContains(response, '<svg')

    @override_settings(EXEMPT_VIEW_PERMISSIONS=[])
    def test_access_map_requires_permission(self):
        self.user.object_permissions.all().delete()
        self.user._perm_cache = None
        response = self.client.get(reverse('plugins:netbox_iec62443:accessmap'))
        self.assertIn(response.status_code, (302, 403))

    @override_settings(EXEMPT_VIEW_PERMISSIONS=[])
    def test_site_tab(self):
        response = self.client.get(reverse('dcim:site_iec62443_accessmap', kwargs={'pk': self.site.pk}))
        self.assertHttpStatus(response, 200)
        self.assertContains(response, 'office to cell')

    @override_settings(EXEMPT_VIEW_PERMISSIONS=[])
    def test_device_panel(self):
        response = self.client.get(self.device.get_absolute_url())
        self.assertHttpStatus(response, 200)
        self.assertContains(response, 'IEC 62443')
        self.assertContains(response, 'Cell A')
        self.assertContains(response, 'office to cell')


class ZoneDeleteProtectedTest(TestCase):
    """A zone with conduits is refused with a message (UI) or 409 (API), not a server error."""
    user_permissions = ('netbox_iec62443.view_zone', 'netbox_iec62443.delete_zone', 'netbox_iec62443.view_conduit')

    @classmethod
    def setUpTestData(cls):
        office = Zone.objects.create(name='Office', slug='office', purdue_level='4')
        cls.cell = Zone.objects.create(name='Cell', slug='cell', purdue_level='1')
        Conduit.objects.create(name='office to cell', source_zone=office, destination_zone=cls.cell, allowed='no')

    @override_settings(EXEMPT_VIEW_PERMISSIONS=[])
    def test_ui_delete_refused(self):
        url = reverse('plugins:netbox_iec62443:zone_delete', kwargs={'pk': self.cell.pk})
        response = self.client.post(url, {'confirm': True}, follow=True)
        self.assertHttpStatus(response, 200)
        self.assertTrue(Zone.objects.filter(pk=self.cell.pk).exists())
        self.assertEqual(Conduit.objects.get().allowed, 'no')

    @override_settings(EXEMPT_VIEW_PERMISSIONS=[])
    def test_api_delete_refused(self):
        from users.models import Token
        token = Token.objects.create(user=self.user)
        url = reverse('plugins-api:netbox_iec62443-api:zone-detail', kwargs={'pk': self.cell.pk})
        response = self.client.delete(url, HTTP_AUTHORIZATION=f'Token {token.key}')
        self.assertHttpStatus(response, 409)
        self.assertTrue(Zone.objects.filter(pk=self.cell.pk).exists())
