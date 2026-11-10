from django.core.exceptions import ValidationError
from django.test import TestCase as DjangoTestCase
from django.test import override_settings

from dcim.models import Interface, Site
from utilities.testing import (
    APIViewTestCases,
    ChangeLoggedFilterSetTestMixin,
    TestCase,
    ViewTestCases,
    create_tags,
    create_test_device,
)

from netbox_iec62443.filtersets import FieldbusFilterSet, IndustrialServiceFilterSet
from netbox_iec62443.models import Fieldbus, IndustrialService, Zone

from .test_views import PluginURLMixin


class IndustrialServiceModelTest(DjangoTestCase):

    @classmethod
    def setUpTestData(cls):
        site = Site.objects.create(name='Site 1', slug='site-1')
        cls.plc = create_test_device('plc-1', site=site)
        cls.other = create_test_device('plc-2', site=site)
        cls.bus = Fieldbus.objects.create(name='Line 1 RS-485', site=site, medium='rs-485', protocol='modbus-rtu')

    def test_default_ports(self):
        svc = IndustrialService(device=self.plc, protocol='modbus-tcp')
        svc.full_clean()
        svc.save()
        self.assertEqual(svc.ports, [502])
        self.assertEqual(svc.role, 'server')
        self.assertIn('Modbus TCP', str(svc))

    def test_serial_has_no_ports(self):
        svc = IndustrialService(device=self.plc, protocol='modbus-rtu', fieldbus=self.bus, address='unit 3')
        svc.full_clean()
        svc.save()
        self.assertEqual(svc.ports, [])
        with self.assertRaises(ValidationError):
            IndustrialService(device=self.plc, protocol='modbus-rtu', ports=[502]).full_clean()

    def test_one_parent(self):
        with self.assertRaises(ValidationError):
            IndustrialService(protocol='s7comm').full_clean()

    def test_interface_of_other_device(self):
        iface = Interface.objects.create(device=self.other, name='eth0', type='1000base-t')
        with self.assertRaises(ValidationError):
            IndustrialService(device=self.plc, protocol='s7comm', interface=iface).full_clean()

    def test_network_protocol_not_on_fieldbus(self):
        with self.assertRaises(ValidationError):
            IndustrialService(device=self.plc, protocol='s7comm', fieldbus=self.bus).full_clean()


class FieldbusViewTest(PluginURLMixin, ViewTestCases.PrimaryObjectViewTestCase):
    model = Fieldbus

    @classmethod
    def setUpTestData(cls):
        site = Site.objects.create(name='Site 1', slug='site-1')
        zone = Zone.objects.create(name='Cell', slug='cell', site=site, purdue_level='1')
        gw = create_test_device('gw-1', site=site)
        Fieldbus.objects.bulk_create([
            Fieldbus(name='Bus 1', site=site, medium='rs-485', protocol='modbus-rtu'),
            Fieldbus(name='Bus 2', site=site, medium='profibus', protocol='profibus-dp'),
            Fieldbus(name='Bus 3', site=site, medium='can', protocol='canopen'),
        ])
        tags = create_tags('Alpha', 'Bravo', 'Charlie')
        cls.form_data = {
            'name': 'Bus X', 'site': site.pk, 'zone': zone.pk, 'medium': 'rs-485', 'protocol': 'modbus-rtu',
            'gateway': gw.pk, 'tags': [t.pk for t in tags],
        }
        cls.csv_data = (
            'name,site,medium,protocol',
            'Bus 4,Site 1,rs-485,modbus-rtu',
            'Bus 5,Site 1,rs-232,',
            'Bus 6,,can,canopen',
        )
        cls.csv_update_data = (
            'id,medium,description',
            f'{Fieldbus.objects.get(name="Bus 1").pk},rs-422,changed',
            f'{Fieldbus.objects.get(name="Bus 2").pk},rs-485,changed',
            f'{Fieldbus.objects.get(name="Bus 3").pk},other,changed',
        )
        cls.bulk_edit_data = {'medium': 'rs-422'}


class IndustrialServiceViewTest(PluginURLMixin, ViewTestCases.PrimaryObjectViewTestCase):
    model = IndustrialService

    @classmethod
    def setUpTestData(cls):
        site = Site.objects.create(name='Site 1', slug='site-1')
        plc = create_test_device('plc-1', site=site)
        hmi = create_test_device('hmi-1', site=site)
        bus = Fieldbus.objects.create(name='Bus 1', site=site, medium='rs-485', protocol='modbus-rtu')
        IndustrialService.objects.create(device=plc, protocol='s7comm', role='server')
        IndustrialService.objects.create(device=hmi, protocol='s7comm', role='client')
        IndustrialService.objects.create(device=plc, protocol='modbus-rtu', role='client', fieldbus=bus)
        tags = create_tags('Alpha', 'Bravo', 'Charlie')
        cls.form_data = {
            'device': plc.pk, 'protocol': 'modbus-tcp', 'role': 'server', 'ports': '502,503',
            'evidence': 'Port 502 open', 'tags': [t.pk for t in tags],
        }
        cls.csv_data = (
            'device,protocol,role,address',
            'plc-1,opc-ua,server,',
            'hmi-1,opc-ua,client,',
            'plc-1,profinet,server,',
        )
        ids = list(IndustrialService.objects.order_by('pk').values_list('pk', flat=True))
        cls.csv_update_data = (
            'id,role,description',
            f'{ids[0]},both,changed',
            f'{ids[1]},both,changed',
            f'{ids[2]},both,changed',
        )
        cls.bulk_edit_data = {'role': 'both'}


class FieldbusAPITest(APIViewTestCases.APIViewTestCase):
    model = Fieldbus
    view_namespace = 'plugins-api:netbox_iec62443'
    graphql_base_name = 'iec62443_fieldbus'
    brief_fields = ['description', 'display', 'id', 'medium', 'name', 'url']
    bulk_update_data = {'medium': 'rs-422'}
    bulk_update_invalid_data = {'medium': 'bogus'}

    @classmethod
    def setUpTestData(cls):
        site = Site.objects.create(name='Site 1', slug='site-1')
        Fieldbus.objects.bulk_create([
            Fieldbus(name='Bus 1', site=site, medium='rs-485'),
            Fieldbus(name='Bus 2', site=site, medium='rs-232'),
            Fieldbus(name='Bus 3', site=site, medium='can'),
        ])
        cls.create_data = [
            {'name': 'Bus 4', 'site': site.pk, 'medium': 'rs-485', 'protocol': 'modbus-rtu'},
            {'name': 'Bus 5', 'medium': 'profibus', 'protocol': 'profibus-dp'},
            {'name': 'Bus 6', 'site': site.pk, 'medium': 'other'},
        ]


class IndustrialServiceAPITest(APIViewTestCases.APIViewTestCase):
    model = IndustrialService
    view_namespace = 'plugins-api:netbox_iec62443'
    graphql_base_name = 'iec62443_industrial_service'
    brief_fields = ['description', 'display', 'id', 'protocol', 'role', 'url']
    bulk_update_data = {'role': 'both', 'address': 'unit 1'}
    bulk_update_invalid_data = {'role': 'bogus'}
    user_permissions = ('dcim.view_device',)

    @classmethod
    def setUpTestData(cls):
        site = Site.objects.create(name='Site 1', slug='site-1')
        plc = create_test_device('plc-1', site=site)
        IndustrialService.objects.create(device=plc, protocol='s7comm')
        IndustrialService.objects.create(device=plc, protocol='modbus-tcp')
        IndustrialService.objects.create(device=plc, protocol='opc-ua')
        cls.create_data = [
            {'device': plc.pk, 'protocol': 'ethernet-ip', 'role': 'server'},
            {'device': plc.pk, 'protocol': 'dnp3', 'role': 'server', 'ports': [20000, 20001]},
            {'device': plc.pk, 'protocol': 'modbus-rtu', 'role': 'client', 'address': 'master'},
        ]


class FieldbusFilterSetTest(DjangoTestCase, ChangeLoggedFilterSetTestMixin):
    queryset = Fieldbus.objects.all()
    filterset = FieldbusFilterSet

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(name='Site 1', slug='site-1')
        cls.zone = Zone.objects.create(name='Cell', slug='cell', site=cls.site)
        cls.gw = create_test_device('gw-1', site=cls.site)
        Fieldbus.objects.create(name='Bus 1', site=cls.site, zone=cls.zone, medium='rs-485', protocol='modbus-rtu',
                                gateway=cls.gw)
        Fieldbus.objects.create(name='Bus 2', site=cls.site, medium='profibus', protocol='profibus-dp')
        Fieldbus.objects.create(name='Bus 3', medium='can')

    def test_site_zone_gateway(self):
        self.assertEqual(self.filterset({'site_id': [self.site.pk]}, self.queryset).qs.count(), 2)
        self.assertEqual(self.filterset({'zone_id': [self.zone.pk]}, self.queryset).qs.count(), 1)
        self.assertEqual(self.filterset({'gateway_id': [self.gw.pk]}, self.queryset).qs.count(), 1)

    def test_medium_protocol(self):
        self.assertEqual(self.filterset({'medium': ['rs-485', 'can']}, self.queryset).qs.count(), 2)
        self.assertEqual(self.filterset({'protocol': ['profibus-dp']}, self.queryset).qs.count(), 1)


class IndustrialServiceFilterSetTest(DjangoTestCase, ChangeLoggedFilterSetTestMixin):
    queryset = IndustrialService.objects.all()
    filterset = IndustrialServiceFilterSet
    ignore_fields = ('ports', 'evidence')

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(name='Site 1', slug='site-1')
        cls.plc = create_test_device('plc-1', site=cls.site)
        cls.hmi = create_test_device('hmi-1', site=cls.site)
        cls.zone = Zone.objects.create(name='Cell', slug='cell', site=cls.site)
        cls.zone.devices.add(cls.plc)
        cls.bus = Fieldbus.objects.create(name='Bus 1', site=cls.site, medium='rs-485')
        IndustrialService.objects.create(device=cls.plc, protocol='s7comm', role='server')
        IndustrialService.objects.create(device=cls.plc, protocol='modbus-rtu', role='client', fieldbus=cls.bus)
        IndustrialService.objects.create(device=cls.hmi, protocol='s7comm', role='client', address='rack 0 slot 1')

    def test_device(self):
        self.assertEqual(self.filterset({'device_id': [self.plc.pk]}, self.queryset).qs.count(), 2)
        self.assertEqual(self.filterset({'device': ['hmi-1']}, self.queryset).qs.count(), 1)

    def test_protocol_role(self):
        self.assertEqual(self.filterset({'protocol': ['s7comm']}, self.queryset).qs.count(), 2)
        self.assertEqual(self.filterset({'role': ['client']}, self.queryset).qs.count(), 2)

    def test_port(self):
        self.assertEqual(self.filterset({'port': 102}, self.queryset).qs.count(), 2)

    def test_fieldbus_site_zone(self):
        self.assertEqual(self.filterset({'fieldbus_id': [self.bus.pk]}, self.queryset).qs.count(), 1)
        self.assertEqual(self.filterset({'site_id': [self.site.pk]}, self.queryset).qs.count(), 3)
        self.assertEqual(self.filterset({'zone_id': [self.zone.pk]}, self.queryset).qs.count(), 2)

    def test_q(self):
        self.assertEqual(self.filterset({'q': 'slot'}, self.queryset).qs.count(), 1)


class DevicePanelServicesTest(TestCase):
    user_permissions = ('dcim.view_device', 'netbox_iec62443.view_zone', 'netbox_iec62443.view_industrialservice',
                        'netbox_iec62443.view_fieldbus')

    @override_settings(EXEMPT_VIEW_PERMISSIONS=[])
    def test_panel_lists_services_and_bus(self):
        site = Site.objects.create(name='Site 1', slug='site-1')
        gw = create_test_device('gw-1', site=site)
        IndustrialService.objects.create(device=gw, protocol='modbus-tcp', role='server')
        Fieldbus.objects.create(name='Line 1 RS-485', site=site, medium='rs-485', gateway=gw)
        response = self.client.get(gw.get_absolute_url())
        self.assertHttpStatus(response, 200)
        self.assertContains(response, 'Modbus TCP')
        self.assertContains(response, 'Line 1 RS-485')
