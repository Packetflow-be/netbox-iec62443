import datetime
import json
from io import StringIO

from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from dcim.models import Interface, Site
from ipam.models import IPAddress, Prefix
from tenancy.models import Contact
from utilities.testing import APITestCase, TestCase, create_test_device

from netbox_iec62443.models import Conduit, Flow, Zone
from netbox_iec62443.rules import RULE_COLUMNS, build_rules

TODAY = timezone.localdate()


def make_rules_site():
    site = Site.objects.create(name='Plant', slug='plant')
    msp = Zone.objects.create(name='MSP', slug='msp', zone_type='external')
    msp.prefixes.add(Prefix.objects.create(prefix='192.0.2.0/24'))
    cell = Zone.objects.create(name='Cell', slug='cell', site=site, purdue_level='1')
    cell.prefixes.add(Prefix.objects.create(prefix='10.1.1.0/24', scope=site))
    control = Zone.objects.create(name='Control', slug='control', site=site, purdue_level='2')
    hmi = create_test_device('hmi-1', site=site)
    iface = Interface.objects.create(device=hmi, name='eth0', type='1000base-t')
    hmi.primary_ip4 = IPAddress.objects.create(address='10.2.2.5/24', assigned_object=iface)
    hmi.save()
    control.devices.add(hmi)  # no prefix: the member's address is used
    fw = create_test_device('fw-1', site=site)
    conduit = Conduit.objects.create(name='Control - Cell', site=site)
    conduit.zones.set([control, cell])
    conduit.enforcing_devices.add(fw)
    contact = Contact.objects.create(name='Plant manager')
    Flow.objects.create(name='hmi s7', source_zone=control, destination_zone=cell, protocol='s7comm',
                        port_mappings=['tcp/102'], access=['read', 'write'], allowed='yes', conduit=conduit,
                        decided_by=contact)
    Flow.objects.create(name='hmi enip', source_zone=control, destination_zone=cell, protocol='ethernet-ip',
                        allowed='yes', conduit=conduit)  # no ports observed: protocol default, tcp and udp
    Flow.objects.create(name='goose', source_zone=control, destination_zone=cell, protocol='iec-61850-goose',
                        allowed='yes')
    Flow.objects.create(name='msp rdp', source_zone=msp, destination_zone=control, protocol='rdp',
                        port_mappings=['tcp/3389'], allowed='yes', remote_access=True,
                        expires=TODAY - datetime.timedelta(days=1))
    Flow.objects.create(name='office smb', source_zone=msp, destination_zone=cell, protocol='smb', allowed='no')
    Flow.objects.create(name='unknown', source_zone=msp, destination_zone=cell)
    return site, fw


class BuildRulesTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.site, cls.fw = make_rules_site()

    def test_allowed_flows_become_rules(self):
        rules, skipped = build_rules()
        by_id = {(r['flow_id'], r['transport']): r for r in rules}
        s7 = next(r for r in rules if r['application'] == 'S7comm')
        self.assertEqual(
            {k: s7[k] for k in ('action', 'source_networks', 'destination_networks', 'transport', 'ports', 'access',
                                'enforced_by', 'decided_by', 'notes')},
            {'action': 'allow', 'source_networks': '10.2.2.5/32', 'destination_networks': '10.1.1.0/24',
             'transport': 'tcp', 'ports': '102', 'access': 'read,write', 'enforced_by': 'fw-1',
             'decided_by': 'Plant manager', 'notes': ''})
        enip = Flow.objects.get(name='hmi enip').pk
        self.assertEqual((by_id[(enip, 'tcp')]['ports'], by_id[(enip, 'udp')]['ports']), ('44818', '2222'))
        self.assertEqual(by_id[(enip, 'tcp')]['rule'], f'{enip}-tcp')
        self.assertIn('protocol default, not observed', by_id[(enip, 'udp')]['notes'])
        goose = next(r for r in rules if r['application'] == 'IEC 61850 GOOSE')
        self.assertEqual(goose['transport'], 'ethernet')
        self.assertIn('layer 2', goose['notes'])
        self.assertEqual(dict(skipped), {'no verdict yet': 1, 'not allowed': 1, 'expired': 1})
        self.assertEqual(list(rules[0]), list(RULE_COLUMNS))

    def test_denied_and_expired_on_request(self):
        rules, skipped = build_rules(include_denied=True)
        denied = {r['application']: r for r in rules if r['action'] == 'deny'}
        self.assertEqual(set(denied), {'RDP', 'SMB'})
        self.assertIn('expired', denied['RDP']['notes'])
        self.assertEqual(rules[-1]['action'], 'deny')  # allows first
        self.assertEqual(dict(skipped), {'no verdict yet': 1})

    def test_per_enforcement_point(self):
        rules, skipped = build_rules(enforced_by=self.fw)
        self.assertEqual({r['application'] for r in rules}, {'S7comm', 'EtherNet/IP (CIP)'})
        self.assertEqual(skipped['enforced elsewhere'], 1)


class RulesEndpointsTest(APITestCase):

    def setUp(self):
        super().setUp()
        self.site, self.fw = make_rules_site()

    def test_api(self):
        url = reverse('plugins-api:netbox_iec62443-api:firewall_rules')
        response = self.client.get(f'{url}?site_id={self.site.pk}', **self.header)
        self.assertHttpStatus(response, status.HTTP_403_FORBIDDEN)
        self.add_permissions('netbox_iec62443.view_flow', 'dcim.view_site', 'dcim.view_device')
        response = self.client.get(f'{url}?site_id={self.site.pk}&device_id={self.fw.pk}', **self.header)
        self.assertHttpStatus(response, status.HTTP_200_OK)
        self.assertEqual(len(response.data['rules']), 3)  # S7comm, EtherNet/IP tcp + udp
        self.assertEqual(response.data['not_exported'], {'enforced elsewhere': 1, 'no verdict yet': 1,
                                                        'not allowed': 1, 'expired': 1})

    def test_command(self):
        out, err = StringIO(), StringIO()
        call_command('iec62443_rules', '--site', 'plant', '--format', 'json', '--include-denied', stdout=out,
                     stderr=err)
        data = json.loads(out.getvalue())
        self.assertEqual(len(data['rules']), 6)
        self.assertEqual(data['not_exported'], {'no verdict yet': 1})
        self.assertIn('6 rules', err.getvalue())
        out = StringIO()
        call_command('iec62443_rules', '--device', 'fw-1', stdout=out, stderr=StringIO())
        self.assertTrue(out.getvalue().startswith(','.join(RULE_COLUMNS)))


class RulesRegisterExportTest(TestCase):
    user_permissions = ('netbox_iec62443.view_zone', 'netbox_iec62443.view_flow', 'dcim.view_site')

    @override_settings(EXEMPT_VIEW_PERMISSIONS=[])
    def test_csv_from_the_site_register(self):
        site, _fw = make_rules_site()
        response = self.client.get(reverse('dcim:site_iec62443_register', kwargs={'pk': site.pk}) + '?export=rules')
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn('plant-iec62443-firewall-rules.csv', response['Content-Disposition'])
        self.assertIn('S7comm', response.content.decode())
