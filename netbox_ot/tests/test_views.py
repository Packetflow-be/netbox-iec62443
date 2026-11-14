import datetime

from django.test import override_settings
from django.urls import reverse

from dcim.models import Site
from tenancy.models import Contact
from utilities.testing import TestCase, ViewTestCases, create_tags, create_test_device

from netbox_ot.models import Conduit, Flow, FlowHop, RiskAssessment, Zone


class PluginURLMixin:
    def _get_base_url(self):
        return f'plugins:netbox_ot:{self.model._meta.model_name}_{{}}'


class ZoneViewTest(PluginURLMixin, ViewTestCases.PrimaryObjectViewTestCase):
    model = Zone
    # An SL vector is posted as "2" or "2,2,2,1,2,1,1" and stored as a list (checked in SecurityLevelFormTest)
    validation_excluded_fields = ('sl_target', 'sl_achieved')

    @classmethod
    def setUpTestData(cls):
        site = Site.objects.create(name='Site 1', slug='site-1')
        device = create_test_device('plc-1', site=site)
        contact = Contact.objects.create(name='Plant manager')
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
            'zone_type': 'ot',
            'purdue_level': '1',
            'sl_target': '2',
            'sl_achieved': '2,2,1,1,2,1,1',
            'accountable': contact.pk,
            'wireless': True,
            'devices': [device.pk],
            'description': 'Controllers of line 1',
            'tags': [t.pk for t in tags],
        }
        cls.csv_data = (
            'name,slug,site,zone_type,purdue_level,parent,sl_target,accountable',
            'Zone 4,zone-4,Site 1,ot,0,,1,Plant manager',
            'Zone 5,zone-5,Site 1,dmz,3.5,Zone 1,"2,2,2,1,2,1,1",',
            'Zone 6,zone-6,,external,5,,,',
        )
        cls.csv_update_data = (
            'id,purdue_level,description',
            f'{Zone.objects.get(slug="zone-1").pk},2,changed',
            f'{Zone.objects.get(slug="zone-2").pk},3,changed',
            f'{Zone.objects.get(slug="zone-3").pk},4,changed',
        )
        cls.bulk_edit_data = {
            'zone_type': 'safety',
            'purdue_level': '3.5',
            'temporary_devices': True,
        }


class ConduitViewTest(PluginURLMixin, ViewTestCases.PrimaryObjectViewTestCase):
    model = Conduit
    validation_excluded_fields = ('sl_target', 'sl_achieved')

    @classmethod
    def setUpTestData(cls):
        site = Site.objects.create(name='Site 1', slug='site-1')
        office = Zone.objects.create(name='Office', slug='office', site=site, purdue_level='4')
        cell = Zone.objects.create(name='Cell', slug='cell', site=site, purdue_level='1')
        dmz = Zone.objects.create(name='DMZ', slug='dmz', site=site, purdue_level='3.5')
        fw = create_test_device('fw-1', site=site)
        for name in ('Conduit 1', 'Conduit 2', 'Conduit 3'):
            Conduit.objects.create(name=name, site=site).zones.set([office, cell])
        tags = create_tags('Alpha', 'Bravo', 'Charlie')
        cls.form_data = {
            'name': 'Conduit X',
            'site': site.pk,
            'zones': sorted([office.pk, dmz.pk, cell.pk]),
            'sl_target': '2',
            'enforcing_devices': [fw.pk],
            'tags': [t.pk for t in tags],
        }
        cls.csv_data = (
            'site,name,zones,sl_target,enforcing_devices',
            'Site 1,Conduit 4,"Office,Cell",2,fw-1',
            'Site 1,Conduit 5,"DMZ,Cell",,',
            'Site 1,Conduit 6,"Office,DMZ,Cell",1,',
        )
        cls.csv_update_data = (
            'id,sl_target,description',
            f'{Conduit.objects.get(name="Conduit 1").pk},3,changed',
            f'{Conduit.objects.get(name="Conduit 2").pk},2,changed',
            f'{Conduit.objects.get(name="Conduit 3").pk},1,changed',
        )
        cls.bulk_edit_data = {
            'description': 'changed',
        }


class FlowViewTest(PluginURLMixin, ViewTestCases.PrimaryObjectViewTestCase):
    model = Flow
    # The ports widget posts JSON rows; the model stores the flat list (checked in test_ports_saved)
    validation_excluded_fields = ('port_mappings',)

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
            Flow(name='Flow 2', source_zone=remote, destination_zone=cell),
            Flow(name='Flow 3', source_zone=cell, destination_zone=office),
        ])
        tags = create_tags('Alpha', 'Bravo', 'Charlie')
        cls.form_data = {
            'name': 'Flow X',
            'source_zone': remote.pk,
            'destination_zone': cell.pk,
            'conduit': conduit.pk,
            'connection': 'reverse-connect',
            'protocol': 's7comm',
            'port_mappings': '[{"protocol": "tcp", "ports": "102"}]',
            'access': ['read', 'write'],
            'remote_access': True,
            'allowed': 'no',
            'decided_by': contact.pk,
            'decided_on': datetime.date(2026, 11, 1),
            'evidence': 'Seen in capture 1',
            'tags': [t.pk for t in tags],
        }
        cls.csv_data = (
            'site,name,source_zone,destination_zone,conduit,protocol,port_mappings,access,allowed,remote_access,'
            'connection,broker_zone,topics',
            'Site 1,Flow 4,Office,Cell,,s7comm,tcp/102,"read,write",no,false,,,',
            'Site 1,Flow 5,Remote,Cell,Remote - Cell,rdp,tcp/3389,,unknown,true,client-server,,',
            'Site 1,Flow 6,Cell,Remote,,mqtt,tcp/8883,write,yes,false,brokered,Office,"line1/cmd/#,line1/recipe"',
        )
        cls.csv_update_data = (
            'id,allowed,description',
            f'{Flow.objects.get(name="Flow 1").pk},yes,changed',
            f'{Flow.objects.get(name="Flow 2").pk},no,changed',
            f'{Flow.objects.get(name="Flow 3").pk},unknown,changed',
        )
        cls.bulk_edit_data = {
            'allowed': 'no',
            'decided_by': contact.pk,
            'review_by': datetime.date(2027, 1, 1),
        }


class FlowHopViewTest(PluginURLMixin, ViewTestCases.PrimaryObjectViewTestCase):
    model = FlowHop

    @classmethod
    def setUpTestData(cls):
        site = Site.objects.create(name='Site 1', slug='site-1')
        msp = Zone.objects.create(name='MSP', slug='msp', zone_type='external')
        cell = Zone.objects.create(name='Cell', slug='cell', site=site, purdue_level='1')
        flow = Flow.objects.create(name='MSP RDP', source_zone=msp, destination_zone=cell, protocol='rdp')
        devices = [create_test_device(f'hop-{i}', site=site) for i in range(4)]
        for i in range(3):
            FlowHop.objects.create(flow=flow, position=i + 1, device=devices[i])
        tags = create_tags('Alpha', 'Bravo', 'Charlie')
        cls.form_data = {
            'flow': flow.pk,
            'position': 4,
            'device': devices[3].pk,
            'tags': [t.pk for t in tags],
        }
        cls.csv_data = (
            'flow,position,device',
            f'{flow.pk},5,hop-0',
            f'{flow.pk},6,hop-1',
            f'{flow.pk},7,hop-2',
        )
        ids = list(FlowHop.objects.order_by('pk').values_list('pk', flat=True))
        cls.csv_update_data = (
            'id,description',
            f'{ids[0]},jump host',
            f'{ids[1]},firewall',
            f'{ids[2]},gateway',
        )
        cls.bulk_edit_data = {
            'description': 'changed',
        }


class AccessMapViewTest(TestCase):
    user_permissions = ('netbox_ot.view_flow', 'netbox_ot.view_zone', 'dcim.view_site',
                        'dcim.view_device')

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(name='Site 1', slug='site-1')
        office = Zone.objects.create(name='Office', slug='office', site=cls.site, purdue_level='4')
        cell = Zone.objects.create(name='Cell A', slug='cell-a', site=cls.site, purdue_level='1')
        cls.device = create_test_device('plc-1', site=cls.site)
        flow = Flow.objects.create(name='office to cell', source_zone=office, destination_zone=cell, allowed='no',
                                   protocol='s7comm', port_mappings=['tcp/102'], access=['write'],
                                   evidence='96243 connections')
        FlowHop.objects.create(flow=flow, position=1, device=create_test_device('fw-1', site=cls.site))
        cell.devices.add(cls.device)

    @override_settings(EXEMPT_VIEW_PERMISSIONS=[])
    def test_access_map_page(self):
        response = self.client.get(reverse('plugins:netbox_ot:accessmap') + f'?site_id={self.site.pk}')
        self.assertHttpStatus(response, 200)
        self.assertContains(response, 'S7comm')
        self.assertContains(response, 'TCP/102')
        self.assertContains(response, 'fw-1')
        self.assertContains(response, 'runs outside any documented conduit')
        self.assertContains(response, '<svg')

    @override_settings(EXEMPT_VIEW_PERMISSIONS=[])
    def test_access_map_requires_permission(self):
        self.user.object_permissions.all().delete()
        self.user._perm_cache = None
        response = self.client.get(reverse('plugins:netbox_ot:accessmap'))
        self.assertIn(response.status_code, (302, 403))

    @override_settings(EXEMPT_VIEW_PERMISSIONS=[])
    def test_site_tab(self):
        response = self.client.get(reverse('dcim:site_ot_accessmap', kwargs={'pk': self.site.pk}))
        self.assertHttpStatus(response, 200)
        self.assertContains(response, 'office to cell')

    @override_settings(EXEMPT_VIEW_PERMISSIONS=[])
    def test_device_panel(self):
        response = self.client.get(self.device.get_absolute_url())
        self.assertHttpStatus(response, 200)
        self.assertContains(response, 'IEC 62443')
        self.assertContains(response, 'office to cell')

    @override_settings(EXEMPT_VIEW_PERMISSIONS=[])
    def test_hop_device_panel(self):
        response = self.client.get(Site.objects.get().devices.get(name='fw-1').get_absolute_url())
        self.assertContains(response, 'Flows through it')


class ZoneDeleteProtectedTest(TestCase):
    """A zone with flows is refused with a message (UI) or 409 (API), not a server error."""
    user_permissions = ('netbox_ot.view_zone', 'netbox_ot.delete_zone', 'netbox_ot.view_flow')

    @classmethod
    def setUpTestData(cls):
        office = Zone.objects.create(name='Office', slug='office', purdue_level='4')
        cls.cell = Zone.objects.create(name='Cell', slug='cell', purdue_level='1')
        Flow.objects.create(name='office to cell', source_zone=office, destination_zone=cls.cell, allowed='no')

    @override_settings(EXEMPT_VIEW_PERMISSIONS=[])
    def test_ui_delete_refused(self):
        url = reverse('plugins:netbox_ot:zone_delete', kwargs={'pk': self.cell.pk})
        response = self.client.post(url, {'confirm': True}, follow=True)
        self.assertHttpStatus(response, 200)
        self.assertTrue(Zone.objects.filter(pk=self.cell.pk).exists())
        self.assertEqual(Flow.objects.get().allowed, 'no')

    @override_settings(EXEMPT_VIEW_PERMISSIONS=[])
    def test_api_delete_refused(self):
        from users.models import Token
        token = Token.objects.create(user=self.user)
        url = reverse('plugins-api:netbox_ot-api:zone-detail', kwargs={'pk': self.cell.pk})
        response = self.client.delete(url, HTTP_AUTHORIZATION=f'Token {token.key}')
        self.assertHttpStatus(response, 409)
        self.assertTrue(Zone.objects.filter(pk=self.cell.pk).exists())


class FlowFormTest(TestCase):
    user_permissions = ('netbox_ot.add_flow', 'netbox_ot.view_flow', 'netbox_ot.view_zone')

    @override_settings(EXEMPT_VIEW_PERMISSIONS=['*'])
    def test_ports_saved(self):
        office = Zone.objects.create(name='Office', slug='office', purdue_level='4')
        cell = Zone.objects.create(name='Cell', slug='cell', purdue_level='1')
        response = self.client.post(reverse('plugins:netbox_ot:flow_add'), {
            'source_zone': office.pk, 'destination_zone': cell.pk, 'protocol': 'ethernet-ip',
            'connection': 'client-server',
            'port_mappings': '[{"protocol": "tcp", "ports": "44818"}, {"protocol": "udp", "ports": "2222"}]',
            'allowed': 'unknown',
        })
        self.assertHttpStatus(response, 302)
        flow = Flow.objects.get()
        self.assertEqual(flow.port_mappings, ['tcp/44818', 'udp/2222'])
        self.assertEqual(flow.name, 'Office -> Cell EtherNet/IP (CIP)')

    @override_settings(EXEMPT_VIEW_PERMISSIONS=['*'])
    def test_zones_name_their_site(self):
        # Zone names repeat from plant to plant: the form shows the site of each zone and starts on the flow's site
        self.add_permissions('netbox_ot.change_flow')
        plant = Site.objects.create(name='Plant A', slug='plant-a')
        Site.objects.create(name='Plant B', slug='plant-b')
        office = Zone.objects.create(name='Office', slug='office', site=plant, purdue_level='3')
        cell = Zone.objects.create(name='Control room', slug='control-room', site=plant, purdue_level='1')
        flow = Flow.objects.create(source_zone=office, destination_zone=cell)
        response = self.client.get(reverse('plugins:netbox_ot:flow_edit', kwargs={'pk': flow.pk}))
        self.assertHttpStatus(response, 200)
        # The dropdown names each zone's site (later 4.7 releases also on the server-rendered option)
        self.assertContains(response, 'ts-parent-field="site"')
        self.assertRegex(response.content.decode(), rf'<option value="{plant.pk}"\s+selected\s*>Plant A<')



class RiskAssessmentViewTest(PluginURLMixin, ViewTestCases.PrimaryObjectViewTestCase):
    model = RiskAssessment

    @classmethod
    def setUpTestData(cls):
        site = Site.objects.create(name='Site 1', slug='site-1')
        cell = Zone.objects.create(name='Cell', slug='cell', site=site, purdue_level='1')
        office = Zone.objects.create(name='Office', slug='office', site=site, purdue_level='4')
        conduit = Conduit.objects.create(name='Office - Cell', site=site)
        conduit.zones.set([cell, office])
        contact = Contact.objects.create(name='Risk owner')
        for day in (1, 2, 3):
            RiskAssessment.objects.create(zone=cell, assessed_on=datetime.date(2026, 1, day))
        tags = create_tags('Alpha', 'Bravo', 'Charlie')
        cls.form_data = {
            'conduit': conduit.pk,
            'kind': 'detailed',
            'status': 'approved',
            'assessed_on': datetime.date(2026, 10, 1),
            'assessed_by': contact.pk,
            'approved_on': datetime.date(2026, 10, 15),
            'approved_by': contact.pk,
            'threats': 'Supplier laptop with malware',
            'unmitigated_risk': 'high',
            'countermeasures': 'Jump host with MFA',
            'residual_risk': 'medium',
            'tolerable_risk': 'medium',
            'tags': [t.pk for t in tags],
        }
        cls.csv_data = (
            'site,zone,conduit,kind,status,assessed_on,residual_risk,tolerable_risk',
            'Site 1,Cell,,initial,draft,2026-02-01,high,medium',
            'Site 1,,Office - Cell,detailed,draft,2026-02-02,,',
            'Site 1,Office,,detailed,draft,2026-02-03,low,low',
        )
        ids = list(RiskAssessment.objects.order_by('pk').values_list('pk', flat=True))
        cls.csv_update_data = (
            'id,tolerable_risk,description',
            f'{ids[0]},low,changed',
            f'{ids[1]},medium,changed',
            f'{ids[2]},high,changed',
        )
        cls.bulk_edit_data = {
            'tolerable_risk': 'medium',
            'next_review': datetime.date(2027, 10, 1),
        }


class SecurityLevelFormTest(TestCase):
    user_permissions = ('netbox_ot.add_zone', 'netbox_ot.view_zone')

    @override_settings(EXEMPT_VIEW_PERMISSIONS=['*'])
    def test_sl_vectors(self):
        url = reverse('plugins:netbox_ot:zone_add')
        response = self.client.post(url, {'name': 'Z', 'slug': 'z', 'zone_type': 'ot', 'sl_target': '2',
                                          'sl_achieved': '{2 2 1 1 2 1 1}'})
        self.assertHttpStatus(response, 302)
        zone = Zone.objects.get(slug='z')
        self.assertEqual(zone.sl_target, [2] * 7)
        self.assertEqual(zone.sl_achieved, [2, 2, 1, 1, 2, 1, 1])
        self.assertEqual(zone.sl_gap, ['SI', 'DC', 'TRE', 'RA'])
        response = self.client.post(url, {'name': 'Y', 'slug': 'y', 'zone_type': 'ot', 'sl_target': '2,2,5'})
        self.assertHttpStatus(response, 200)  # form error, not saved
        self.assertFalse(Zone.objects.filter(slug='y').exists())


class ChecksAndRegisterViewTest(TestCase):
    user_permissions = ('netbox_ot.view_zone', 'netbox_ot.view_conduit', 'netbox_ot.view_flow',
                        'netbox_ot.view_riskassessment', 'dcim.view_site', 'dcim.view_device')

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(name='Site 1', slug='site-1')
        office = Zone.objects.create(name='Office', slug='office', site=cls.site, purdue_level='4',
                                     zone_type='enterprise')
        cell = Zone.objects.create(name='Cell', slug='cell', site=cls.site, purdue_level='1', sl_target=[2] * 7)
        cell.devices.add(create_test_device('plc-1', site=cls.site))
        Flow.objects.create(name='office to cell', source_zone=office, destination_zone=cell, allowed='yes')

    @override_settings(EXEMPT_VIEW_PERMISSIONS=[])
    def test_checks_page(self):
        response = self.client.get(reverse('plugins:netbox_ot:checks') + f'?site_id={self.site.pk}')
        self.assertHttpStatus(response, 200)
        self.assertContains(response, 'runs outside any documented conduit')
        self.assertContains(response, 'flow-without-conduit')

    @override_settings(EXEMPT_VIEW_PERMISSIONS=[])
    def test_register_tab_and_csv(self):
        url = reverse('dcim:site_ot_register', kwargs={'pk': self.site.pk})
        response = self.client.get(url)
        self.assertHttpStatus(response, 200)
        self.assertContains(response, '{2 2 2 2 2 2 2}')
        self.assertContains(response, 'office to cell')
        response = self.client.get(url + '?export=zones')
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        lines = response.content.decode().splitlines()
        self.assertTrue(lines[0].startswith('zone,type,purdue_level'))
        self.assertTrue(any(line.startswith('Cell,OT (control),1') for line in lines))
