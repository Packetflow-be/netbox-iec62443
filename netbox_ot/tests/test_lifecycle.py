"""
End of support from netbox-lifecycle (netbox_ot/lifecycle.py). The tests that need netbox-lifecycle run in the
CI job that installs the companion plugins; the others run everywhere.
"""
import datetime
import unittest

from django.apps import apps
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from dcim.models import Device, DeviceRole, DeviceType, Manufacturer, Module, ModuleBay, ModuleType, Site
from extras.models import CustomField
from utilities.testing import TestCase as NetBoxTestCase

from netbox_ot import lifecycle
from netbox_ot.checks import run_checks
from netbox_ot.customfields import FIRMWARE_CF_NAME, get_firmware_version
from netbox_ot.models import Zone
from netbox_ot.register import build_register

LIFECYCLE = apps.is_installed('netbox_lifecycle')


def days(n):
    return timezone.localdate() + datetime.timedelta(days=n)


class Plant:
    """A cell zone at SL-T 2 with a PLC (CPU module) and an HMI, an office zone at SL-T 1 with a PC."""

    @classmethod
    def build(cls, test):
        test.site = Site.objects.create(name='Plant', slug='plant')
        maker = Manufacturer.objects.create(name='Maker', slug='maker')
        role = DeviceRole.objects.create(name='OT', slug='ot')
        test.plc_type = DeviceType.objects.create(manufacturer=maker, model='PLC rack', slug='plc-rack')
        test.hmi_type = DeviceType.objects.create(manufacturer=maker, model='HMI', slug='hmi')
        test.pc_type = DeviceType.objects.create(manufacturer=maker, model='PC', slug='pc')
        test.cpu_type = ModuleType.objects.create(manufacturer=maker, model='CPU 1515')
        test.plc = Device.objects.create(name='plc1', site=test.site, device_type=test.plc_type, role=role)
        bay = ModuleBay.objects.create(device=test.plc, name='Slot 1')
        Module.objects.create(device=test.plc, module_bay=bay, module_type=test.cpu_type)
        test.hmi = Device.objects.create(name='hmi1', site=test.site, device_type=test.hmi_type, role=role)
        test.pc = Device.objects.create(name='pc1', site=test.site, device_type=test.pc_type, role=role)
        test.cell = Zone.objects.create(name='Cell', slug='cell', site=test.site, purdue_level='1', sl_target=[2] * 7)
        test.cell.devices.set([test.plc, test.hmi])
        test.office = Zone.objects.create(name='Office', slug='office', site=test.site, purdue_level='4',
                                          sl_target=[1] * 7)
        test.office.devices.set([test.pc])


class WithoutLifecycleTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        Plant.build(cls)

    @unittest.skipIf(LIFECYCLE, 'netbox-lifecycle is installed')
    def test_nothing_without_the_plugin(self):
        self.assertFalse(lifecycle.installed())
        self.assertEqual(lifecycle.end_of_support([self.plc]), {})
        self.assertFalse([f for f in run_checks(site=self.site) if f.check.startswith('end-of-support')])
        zones = {row['zone']: row for row in build_register(self.site)['zones']}
        self.assertEqual(zones['Cell']['end_of_support'], '')

    def test_firmware_custom_field(self):
        cf = CustomField.objects.get(name=FIRMWARE_CF_NAME)
        self.assertEqual({ot.model for ot in cf.object_types.all()}, {'device', 'module'})
        self.plc.custom_field_data[FIRMWARE_CF_NAME] = 'V2.9.4'
        self.assertEqual(get_firmware_version(self.plc), 'V2.9.4')
        self.assertEqual(get_firmware_version(self.hmi), '')


@unittest.skipUnless(LIFECYCLE, 'needs netbox-lifecycle')
class LifecycleTest(NetBoxTestCase):

    @classmethod
    def setUpTestData(cls):
        Plant.build(cls)
        HardwareLifecycle = apps.get_model('netbox_lifecycle', 'HardwareLifecycle')
        # The rack is supported for years, its CPU module lost security fixes last month
        HardwareLifecycle.objects.create(assigned_object=cls.plc_type, end_of_support=days(2000))
        HardwareLifecycle.objects.create(assigned_object=cls.cpu_type, end_of_security=days(-30),
                                         end_of_support=days(400))
        HardwareLifecycle.objects.create(assigned_object=cls.hmi_type, end_of_support=days(100))
        HardwareLifecycle.objects.create(assigned_object=cls.pc_type, end_of_support=days(-500))

    def test_earliest_date_of_device_and_modules(self):
        ends = lifecycle.end_of_support([self.plc, self.hmi, self.pc])
        self.assertEqual(ends[self.plc.pk].date, days(-30))
        self.assertEqual(ends[self.plc.pk].kind, 'security')
        self.assertEqual(ends[self.plc.pk].source, self.cpu_type)
        self.assertTrue(ends[self.plc.pk].passed)
        self.assertEqual(ends[self.hmi.pk].kind, 'support')
        self.assertTrue(ends[self.hmi.pk].ahead)

    def test_checks_only_in_zones_with_sl_target_2(self):
        findings = run_checks(site=self.site)
        past = [f.obj for f in findings if f.check == 'end-of-support']
        ahead = [f.obj for f in findings if f.check == 'end-of-support-ahead']
        # The PC is long past its end of support, but its zone has SL-T 1
        self.assertEqual(past, [self.plc])
        self.assertEqual(ahead, [self.hmi])
        message = next(f.message for f in findings if f.check == 'end-of-support')
        self.assertIn('CPU 1515', message)

    def test_register_column(self):
        zones = {row['zone']: row for row in build_register(self.site)['zones']}
        self.assertCountEqual(zones['Cell']['end_of_support'].split(', '),
                              [f'plc1 ({days(-30).isoformat()})', f'hmi1 ({days(100).isoformat()})'])

    def test_device_panel(self):
        self.user.is_superuser = True
        self.user.save()
        response = self.client.get(reverse('dcim:device', kwargs={'pk': self.plc.pk}))
        self.assertContains(response, 'End of support')
        self.assertContains(response, days(-30).isoformat())
