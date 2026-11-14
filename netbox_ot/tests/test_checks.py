import datetime
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from dcim.models import Interface, Site
from extras.models import CustomField
from ipam.models import IPAddress, Prefix
from tenancy.models import Contact
from utilities.testing import create_test_device

from netbox_ot.checks import CHECKS, run_checks
from netbox_ot.customfields import PURDUE_CF_NAME, SLC_CF_NAME
from netbox_ot.models import Conduit, Flow, RequirementStatus, RiskAssessment, SystemRequirement, Zone

TODAY = timezone.localdate()


def device(name, site, ip=None, level=None, slc=None):
    d = create_test_device(name, site=site)
    if ip:
        iface = Interface.objects.create(device=d, name='eth0', type='1000base-t')
        d.primary_ip4 = IPAddress.objects.create(address=f'{ip}/24', assigned_object=iface)
    if level:
        d.custom_field_data[PURDUE_CF_NAME] = level
    if slc:
        d.custom_field_data[SLC_CF_NAME] = slc
    d.save()
    return d


class ChecksTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(name='Plant', slug='plant')
        cls.contact = Contact.objects.create(name='Plant manager')
        cls.office = Zone.objects.create(name='Office', slug='office', site=cls.site, purdue_level='4',
                                         zone_type='enterprise')
        cls.cell = Zone.objects.create(name='Cell', slug='cell', site=cls.site, purdue_level='2', sl_target=[2] * 7,
                                       sl_achieved=[2, 2, 1, 2, 2, 2, 2], accountable=cls.contact)
        cls.sub = Zone.objects.create(name='Cell safety', slug='cell-safety', site=cls.site, purdue_level='1',
                                      zone_type='safety', parent=cls.cell)
        cls.cell.prefixes.add(Prefix.objects.create(prefix='10.1.1.0/24', scope=cls.site))
        cls.office.prefixes.add(Prefix.objects.create(prefix='10.2.2.0/24', scope=cls.site))
        # A PLC at level 1 in a level-2 zone, with an office address and too little capability
        cls.plc = device('plc-1', cls.site, ip='10.2.2.50', level='1', slc='2,2,2,2,1,2,2')
        cls.cell.devices.add(cls.plc)
        cls.sub.devices.add(cls.plc)  # its own sub-zone: not "several zones"
        cls.laptop = device('laptop-1', cls.site, ip='10.1.1.99', level='4')
        cls.cell.devices.add(cls.laptop)
        cls.office.devices.add(cls.laptop)  # two unrelated zones
        cls.hmi = device('hmi-1', cls.site, level='2')
        cls.office.devices.add(cls.hmi)  # control asset in an enterprise zone
        cls.loose = device('loose-1', cls.site, ip='10.1.1.77')  # in no zone
        device('patch-panel', cls.site)  # no address, no level: not reported
        conduit = Conduit.objects.create(name='Office - Cell', site=cls.site, sl_target=[1] * 7)
        conduit.zones.set([cls.office, cls.cell])
        Flow.objects.create(name='expired', source_zone=cls.office, destination_zone=cls.cell, allowed='yes',
                            expires=TODAY - datetime.timedelta(days=1), conduit=conduit, decided_by=cls.contact)
        Flow.objects.create(name='supplier', source_zone=cls.office, destination_zone=cls.cell, allowed='yes',
                            remote_access=True)
        # Writes to the cell through a broker in the office, topics not recorded
        Flow.objects.create(name='recipes', source_zone=cls.office, destination_zone=cls.cell, connection='brokered',
                            broker_zone=cls.office, access=['write'], conduit=conduit)
        Flow.objects.create(name='old', source_zone=cls.cell, destination_zone=cls.office,
                            last_seen=timezone.now() - datetime.timedelta(days=365))
        # Straight from the office into the safety zone: an undecided write and an allowed read
        Flow.objects.create(name='office writes safety', source_zone=cls.office, destination_zone=cls.sub,
                            access=['read', 'write'])
        Flow.objects.create(name='office reads safety', source_zone=cls.office, destination_zone=cls.sub,
                            access=['read'], allowed='yes', decided_by=cls.contact)
        # A supplier is outside the system under consideration: no SL-T, owner or risk assessment asked
        Zone.objects.create(name='Supplier', slug='supplier', site=cls.site, zone_type='external')
        RiskAssessment.objects.create(zone=cls.cell, assessed_on=TODAY - datetime.timedelta(days=400),
                                      status='approved', approved_on=TODAY - datetime.timedelta(days=399),
                                      residual_risk='high', tolerable_risk='medium', next_review=TODAY)

    def test_sl_capability_custom_field(self):
        cf = CustomField.objects.get(name=SLC_CF_NAME)
        self.assertEqual(sorted(f'{ot.app_label}.{ot.model}' for ot in cf.object_types.all()),
                         ['dcim.device', 'dcim.devicetype'])

    def _found(self, check_id):
        return {f.message for f in run_checks(site=self.site, checks=[check_id])}

    def test_every_check_runs_and_finds_its_case(self):
        # IEC 62443-3-3 requirements with a loaded SL: one not met although the cell claims its SL-A, one unassessed
        sr11 = SystemRequirement.objects.create(identifier='SR 1.1', foundational_requirement='iac', security_level=1)
        SystemRequirement.objects.create(identifier='SR 1.2', foundational_requirement='iac', security_level=2)
        RequirementStatus.objects.create(zone=self.cell, requirement=sr11, status='not-met')
        found = {f.check for f in run_checks(site=self.site)}
        # The end-of-support checks need netbox-lifecycle data: test_lifecycle.py
        self.assertEqual(found, set(CHECKS) - {'end-of-support', 'end-of-support-ahead'})

    def test_address_in_other_zone(self):
        self.assertEqual(self._found('address-in-other-zone'), {
            'plc-1 (10.2.2.50) is in zone Cell, but its address is in prefix 10.2.2.0/24 of zone Office',
            'plc-1 (10.2.2.50) is in zone Cell safety, but its address is in prefix 10.2.2.0/24 of zone Office',
            'laptop-1 (10.1.1.99) is in zone Office, but its address is in prefix 10.1.1.0/24 of zone Cell',
        })

    def test_levels(self):
        self.assertEqual(self._found('asset-below-zone-level'), {
            "plc-1 is at Purdue level 1, below level 2 of its zone Cell (a zone's level is its most critical one)",
            "hmi-1 is at Purdue level 2, below level 4 of its zone Office (a zone's level is its most critical one)",
        })
        self.assertEqual(self._found('level-vs-zone-type'), {
            'hmi-1 (level 2) is a control asset in the Enterprise zone Office',
            'laptop-1 (level 4) is an enterprise asset in the OT (control) zone Cell',
        })

    def test_zone_membership(self):
        self.assertEqual(self._found('asset-in-several-zones'), {'laptop-1 is in zones Cell, Office'})
        self.assertEqual(self._found('asset-without-zone'), {'loose-1 at Plant is in no zone'})

    def test_security_levels(self):
        self.assertEqual(self._found('sl-gap'), {'Cell: SL-A {2 2 1 2 2 2 2} is below SL-T {2 2 2 2 2 2 2} in SI'})
        self.assertEqual(self._found('capability-below-target'), {
            'plc-1 SL-C {2 2 2 2 1 2 2} is below SL-T {2 2 2 2 2 2 2} of zone Cell in RDF',
        })
        self.assertEqual(len(self._found('conduit-below-zone-sl')), 1)
        self.assertEqual(self._found('conduit-without-enforcement'),
                         {'Office - Cell names no device or VM that enforces it'})

    def test_flows_and_risk(self):
        self.assertEqual(len(self._found('expired-access')), 1)
        self.assertEqual(self._found('remote-access-without-expiry'),
                         {'supplier allows remote access with no end date'})
        self.assertEqual(len(self._found('flow-without-conduit')), 4)
        self.assertEqual(self._found('verdict-without-decider'), {'supplier is marked yes without who decided it'})
        self.assertEqual(len(self._found('stale-flow')), 1)
        self.assertEqual(len(self._found('residual-above-tolerable')), 1)
        self.assertEqual(len(self._found('risk-assessment-due')), 1)
        self.assertEqual(self._found('no-risk-assessment'), {'Office has no approved risk assessment',
                                                             'Cell safety has no approved risk assessment'})

    def test_exposure(self):
        from netbox_ot.accessmap import attention
        from netbox_ot.filtersets import FlowFilterSet
        self.assertEqual(self._found('undecided-into-control'), {
            'office writes safety reaches control zone Cell safety (write; from the Enterprise zone Office) and nobody '
            'decided whether it is allowed',
        })
        self.assertEqual(self._found('outside-into-control'), {
            'office reads safety is allowed straight from the Enterprise zone Office into control zone Cell safety, '
            'without passing a supervisory zone',
        })
        counts = attention(Flow.objects.filter(source_zone__site=self.site))
        self.assertEqual((counts['undecided_into_control'], counts['outside_into_control']), (1, 1))
        for name, expected in (('undecided_into_control', ['office writes safety']),
                               ('outside_into_control', ['office reads safety'])):
            qs = FlowFilterSet({name: True}, Flow.objects.all()).qs
            self.assertEqual(list(qs.values_list('name', flat=True)), expected)
        # The paperwork checks leave the external zone out
        for check_id in ('no-sl-target', 'no-accountable', 'no-risk-assessment'):
            self.assertFalse([m for m in self._found(check_id) if m.startswith('Supplier')], check_id)

    def test_access_map_puts_writes_first_within_a_verdict(self):
        from netbox_ot.accessmap import access_map_flows
        site = Site.objects.create(name='Order', slug='order')
        hmi = Zone.objects.create(name='HMI', slug='hmi', site=site, purdue_level='2')
        plc = Zone.objects.create(name='PLC', slug='plc', site=site, purdue_level='1')
        office = Zone.objects.create(name='Office', slug='office-o', site=site, purdue_level='4',
                                     zone_type='enterprise')
        Flow.objects.create(name='a hmi reads', source_zone=hmi, destination_zone=plc, access=['read'])
        Flow.objects.create(name='b office reads', source_zone=office, destination_zone=plc, access=['read'])
        Flow.objects.create(name='c hmi writes', source_zone=hmi, destination_zone=plc, access=['write'])
        Flow.objects.create(name='d office writes', source_zone=office, destination_zone=plc, access=['write'])
        self.assertEqual([f.name for f in access_map_flows(site=site)],
                         ['d office writes', 'c hmi writes', 'b office reads', 'a hmi reads'])

    def test_a_clean_site_has_no_errors_or_warnings(self):
        site = Site.objects.create(name='Clean', slug='clean')
        fw = create_test_device('fw-clean', site=site)
        a = Zone.objects.create(name='A', slug='a', site=site, purdue_level='1', sl_target=[1] * 7,
                                accountable=self.contact)
        b = Zone.objects.create(name='B', slug='b', site=site, purdue_level='3', sl_target=[1] * 7,
                                accountable=self.contact)
        conduit = Conduit.objects.create(name='A - B', site=site, sl_target=[1] * 7, accountable=self.contact)
        conduit.zones.set([a, b])
        conduit.enforcing_devices.add(fw)
        Flow.objects.create(source_zone=b, destination_zone=a, conduit=conduit, allowed='no', decided_by=self.contact)
        for zone in (a, b):
            RiskAssessment.objects.create(zone=zone, assessed_on=TODAY, status='approved', approved_on=TODAY,
                                          residual_risk='low', tolerable_risk='medium')
        self.assertEqual(run_checks(site=site), [])

    def test_command(self):
        out = StringIO()
        with self.assertRaises(SystemExit) as exit_:
            call_command('ot_check', '--site', 'plant', stdout=out)
        self.assertEqual(exit_.exception.code, 1)
        self.assertIn('ERROR    expired-access', out.getvalue())
        out = StringIO()
        call_command('ot_check', '--site', 'plant', '--check', 'stale-flow', '--fail-on', 'warning', '--json',
                     stdout=out)
        self.assertIn('"check": "stale-flow"', out.getvalue())
