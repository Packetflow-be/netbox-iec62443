from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from dcim.models import Device, Site
from ipam.models import IPAddress, Prefix
from tenancy.models import Contact

from netbox_ot.checks import run_checks
from netbox_ot.models import Conduit, Flow, FlowHop, IndustrialService, RiskAssessment, Zone


class DemoCommandTest(TestCase):

    def test_create_and_delete(self):
        call_command('ot_demo', stdout=StringIO())
        site = Site.objects.get(slug='iec62443-demo')
        self.assertEqual(Zone.objects.count(), 6)
        self.assertEqual(Conduit.objects.count(), 4)
        self.assertEqual(Flow.objects.count(), 8)
        remote = Flow.objects.get(name='MSP maintenance RDP')
        self.assertEqual([str(h.hop) for h in remote.hops.all()],
                         ['IEC 62443 demo MSP IPsec', 'demo-jump-1', 'demo-fw-1'])
        self.assertTrue(IndustrialService.objects.filter(service__isnull=False).exists())
        self.assertEqual(RiskAssessment.objects.count(), 3)
        # The demo shows the checks at work, errors included
        found = {f.check for f in run_checks(site=site)}
        self.assertTrue({'expired-access', 'residual-above-tolerable', 'asset-without-zone', 'sl-gap',
                         'capability-below-target', 'flow-without-conduit'} <= found)
        self.assertNotIn('asset-below-zone-level', found)
        with self.assertRaisesRegex(CommandError, 'already exists'):
            call_command('ot_demo', stdout=StringIO())

        call_command('ot_demo', '--delete', stdout=StringIO())
        self.assertFalse(Site.objects.filter(slug='iec62443-demo').exists())
        for model in (Zone, Conduit, Flow, FlowHop, IndustrialService, RiskAssessment):
            self.assertEqual(model.objects.count(), 0, model)
        self.assertFalse(Device.objects.filter(name__startswith='demo-').exists())
        self.assertFalse(IPAddress.objects.filter(description='IEC 62443 demo').exists())
        self.assertFalse(Prefix.objects.filter(description__startswith='IEC 62443 demo').exists())
        self.assertFalse(Contact.objects.filter(description='IEC 62443 demo').exists())
        call_command('ot_demo', stdout=StringIO())  # and again
