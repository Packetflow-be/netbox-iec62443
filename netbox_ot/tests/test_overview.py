from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from dcim.models import Site
from tenancy.models import Contact
from utilities.testing import APITestCase, TestCase

from netbox_ot.models import Conduit, RequirementStatus, RiskAssessment, SystemRequirement, Zone
from netbox_ot.overview import build_overview, overview_json, radar_svg


def _plant():
    """A site with four zones and a conduit: one at target, one below, one not assessed, one without a target."""
    site = Site.objects.create(name='Site 1', slug='site-1')
    cell = Zone.objects.create(name='Cell', slug='cell', site=site, purdue_level='1',
                               sl_target=[2, 2, 2, 1, 2, 1, 2], sl_achieved=[2, 1, 2, 1, 1, 1, 2])
    control = Zone.objects.create(name='Control', slug='control', site=site, purdue_level='2',
                                  sl_target=[2] * 7, sl_achieved=[2] * 7)
    Zone.objects.create(name='DMZ', slug='dmz', site=site, purdue_level='3.5', sl_target=[1] * 7)
    office = Zone.objects.create(name='Office', slug='office', site=site, purdue_level='4')
    conduit = Conduit.objects.create(name='Control - Cell', site=site, sl_target=[2] * 7, sl_achieved=[1] + [2] * 6)
    conduit.zones.set([control, cell])
    owner = Contact.objects.create(name='Risk owner')
    approved = {'status': 'approved', 'approved_on': '2026-03-02', 'approved_by': owner}
    # The newer approved assessment counts; the draft never does
    RiskAssessment.objects.create(zone=cell, assessed_on='2026-01-01', unmitigated_risk='critical',
                                  residual_risk='critical', tolerable_risk='medium', **approved)
    RiskAssessment.objects.create(zone=cell, assessed_on='2026-03-01', unmitigated_risk='critical',
                                  residual_risk='high', tolerable_risk='medium', **approved)
    RiskAssessment.objects.create(zone=control, assessed_on='2026-03-01', unmitigated_risk='high',
                                  residual_risk='low', tolerable_risk='medium', **approved)
    RiskAssessment.objects.create(zone=office, assessed_on='2026-03-01', unmitigated_risk='medium')
    sr = {identifier: SystemRequirement.objects.create(identifier=identifier)
          for identifier in ('SR 1.1', 'SR 1.2', 'SR 5.1', 'SR 5.2')}
    RequirementStatus.objects.create(zone=cell, requirement=sr['SR 1.1'], status='met')
    RequirementStatus.objects.create(zone=cell, requirement=sr['SR 1.2'], status='not-met')
    RequirementStatus.objects.create(zone=cell, requirement=sr['SR 5.1'], status='compensated',
                                     countermeasure='Unidirectional gateway')
    RequirementStatus.objects.create(conduit=conduit, requirement=sr['SR 5.2'], status='not-applicable')
    return site, cell


class OverviewTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.site, cls.cell = _plant()

    def test_security_levels(self):
        overview = build_overview(self.site)
        self.assertEqual(overview['zones'], {
            'total': 4, 'with_target': 3, 'at_target': 1, 'below_target': 1, 'not_assessed': 1})
        # The average is over the two zones with a target and an achieved level
        axes = {a['fr']: a for a in overview['axes']}
        self.assertEqual((axes['IAC']['target'], axes['IAC']['achieved'], axes['IAC']['below']), (2, 2, 0))
        self.assertEqual((axes['UC']['target'], axes['UC']['achieved'], axes['UC']['below']), (2, 1.5, 1))
        self.assertEqual((axes['DC']['target'], axes['DC']['achieved']), (1.5, 1.5))
        self.assertEqual(axes['RDF']['measured'], 2)
        self.assertEqual(overview['furthest']['fr'], 'UC')
        # Furthest below target first, then not assessed, no target, and at target last
        self.assertEqual([(r['name'], r['state'], r['gap']) for r in overview['levels']], [
            ('Cell', 'gap', 2), ('Control - Cell', 'gap', 1), ('DMZ', 'no-achieved', None),
            ('Office', 'no-target', None), ('Control', 'met', 0)])
        self.assertEqual(overview['levels'][0]['below'], ['UC', 'RDF'])

    def test_one_zone(self):
        overview = build_overview(self.site, zone=self.cell)
        self.assertEqual(overview['focus'], self.cell)
        self.assertEqual([a['target'] for a in overview['axes']], [2, 2, 2, 1, 2, 1, 2])
        self.assertEqual([a['achieved'] for a in overview['axes']], [2, 1, 2, 1, 1, 1, 2])
        # A zone of another site is ignored
        other = Zone.objects.create(name='Elsewhere', slug='elsewhere', sl_target=[4] * 7,
                                    site=Site.objects.create(name='Site 2', slug='site-2'))
        self.assertIsNone(build_overview(self.site, zone=other)['focus'])

    def test_requirements(self):
        requirements = build_overview(self.site)['requirements']
        self.assertEqual((requirements['total'], requirements['satisfied'], requirements['percent']), (4, 3, 75))
        self.assertEqual((requirements['not_met'], requirements['open']), (1, 0))
        per_fr = {fr['fr']: fr for fr in requirements['per_fr']}
        self.assertEqual((per_fr['IAC']['total'], per_fr['IAC']['percent']), (2, 50))
        self.assertEqual((per_fr['RDF']['total'], per_fr['RDF']['percent']), (2, 100))
        self.assertIsNone(per_fr['SI']['percent'])

    def test_requirements_without_status(self):
        # Once the level of a requirement is loaded, it counts for every zone whose target reaches it
        SystemRequirement.objects.filter(identifier='SR 5.2').update(security_level=2)
        requirements = build_overview(self.site)['requirements']
        # Cell and Control have RDF 2 and no status for SR 5.2; the conduit has one
        self.assertEqual(requirements['open'], 2)
        self.assertEqual(requirements['total'], 6)

    def test_risk(self):
        risk = build_overview(self.site)['risk']
        self.assertEqual((risk['assessed'], risk['subjects']), (2, 5))
        levels = {row['level']: (row['unmitigated'], row['residual']) for row in risk['levels']}
        self.assertEqual(levels, {'critical': (1, 0), 'high': (1, 1), 'medium': (0, 0), 'low': (0, 1)})
        self.assertEqual([row['level'] for row in risk['levels']], ['critical', 'high', 'medium', 'low'])
        self.assertEqual([(a['name'], a['residual_risk'], a['tolerable_risk']) for a in risk['above_tolerable']],
                         [('Cell', 'High', 'Medium')])
        # The draft assessment of Office does not count
        self.assertEqual(sorted(w['name'] for w in risk['without_assessment']), ['Control - Cell', 'DMZ', 'Office'])

    def test_empty_site(self):
        overview = build_overview(Site.objects.create(name='Empty', slug='empty'))
        self.assertEqual(overview['chart'], '')
        self.assertEqual(overview['levels'], [])
        self.assertIsNone(overview['furthest'])
        self.assertIsNone(overview['requirements']['percent'])
        self.assertEqual(overview['risk']['assessed'], 0)

    def test_chart(self):
        overview = build_overview(self.site)
        svg = overview['chart']
        self.assertTrue(svg.startswith('<svg class="ot-radar"'))
        self.assertEqual(svg.count('class="spoke"'), 7)
        self.assertEqual(svg.count('class="ring"'), 2)  # the highest level drawn is SL 2
        self.assertEqual(svg.count('<circle'), 7)
        self.assertIn('1.5 / 2 ▼', svg)
        self.assertNotIn('<script', svg)
        # A target without an achieved level draws the outline only
        svg = radar_svg(build_overview(self.site, zone=Zone.objects.get(slug='dmz'))['axes'])
        self.assertIn('class="target"', svg)
        self.assertNotIn('class="achieved"', svg)
        self.assertNotIn('<circle', svg)

    def test_json_has_no_objects(self):
        import json
        data = overview_json(build_overview(self.site))
        json.dumps(data)
        self.assertNotIn('chart', data)
        self.assertEqual(data['furthest_from_target'], 'UC')
        self.assertEqual(data['requirements']['per_fr'][0]['counts']['no-status'], 0)

    def test_restricted_to_what_the_user_can_view(self):
        self.add_permissions('netbox_ot.view_conduit')
        overview = build_overview(self.site, user=self.user)
        self.assertEqual([r['name'] for r in overview['levels']], ['Control - Cell'])
        self.assertEqual(overview['zones']['total'], 0)


class OverviewViewTest(TestCase):
    user_permissions = ('netbox_ot.view_zone', 'netbox_ot.view_conduit', 'netbox_ot.view_riskassessment',
                        'netbox_ot.view_requirementstatus', 'dcim.view_site')

    @classmethod
    def setUpTestData(cls):
        cls.site, cls.cell = _plant()

    @override_settings(EXEMPT_VIEW_PERMISSIONS=[])
    def test_tab(self):
        url = reverse('dcim:site_ot_overview', kwargs={'pk': self.site.pk})
        response = self.client.get(url)
        self.assertHttpStatus(response, 200)
        self.assertContains(response, '<svg class="ot-radar"')
        self.assertContains(response, 'Average over 2 zones')
        self.assertContains(response, 'Furthest from target: FR 2 Use control (UC).')
        self.assertContains(response, '75%')
        self.assertContains(response, 'Without an approved assessment')
        response = self.client.get(f'{url}?zone={self.cell.pk}')
        self.assertHttpStatus(response, 200)
        self.assertContains(response, 'Zone Cell.')
        self.assertContains(response, 'Show the site average')
        # Anything but a zone of this site falls back to the site average
        for value in ('abc', '999999'):
            response = self.client.get(f'{url}?zone={value}')
            self.assertHttpStatus(response, 200)
            self.assertContains(response, 'Average over 2 zones')

    @override_settings(EXEMPT_VIEW_PERMISSIONS=[])
    def test_tab_shows_on_a_site_with_zones_only(self):
        response = self.client.get(reverse('dcim:site', kwargs={'pk': self.site.pk}))
        self.assertContains(response, 'OT overview')
        empty = Site.objects.create(name='Empty', slug='empty')
        response = self.client.get(reverse('dcim:site', kwargs={'pk': empty.pk}))
        self.assertNotContains(response, 'OT overview')

    @override_settings(EXEMPT_VIEW_PERMISSIONS=[])
    def test_site_without_levels(self):
        site = Site.objects.create(name='Bare', slug='bare')
        Zone.objects.create(name='Only', slug='only', site=site)
        response = self.client.get(reverse('dcim:site_ot_overview', kwargs={'pk': site.pk}))
        self.assertHttpStatus(response, 200)
        self.assertContains(response, 'Nothing to draw yet')
        self.assertContains(response, 'No requirement statuses yet')
        self.assertContains(response, 'No approved risk assessment yet')


class OverviewAPITest(APITestCase):

    @classmethod
    def setUpTestData(cls):
        cls.site, cls.cell = _plant()

    def test_overview(self):
        url = reverse('plugins-api:netbox_ot-api:overview')
        response = self.client.get(f'{url}?site_id={self.site.pk}', **self.header)
        self.assertHttpStatus(response, status.HTTP_403_FORBIDDEN)
        self.add_permissions('netbox_ot.view_zone', 'netbox_ot.view_conduit', 'netbox_ot.view_riskassessment',
                             'netbox_ot.view_requirementstatus', 'dcim.view_site')
        response = self.client.get(f'{url}?site_id={self.site.pk}', **self.header)
        self.assertHttpStatus(response, status.HTTP_200_OK)
        self.assertEqual(response.data['site']['name'], 'Site 1')
        self.assertEqual(response.data['zones']['at_target'], 1)
        self.assertEqual(response.data['security_levels'][1]['achieved'], 1.5)
        self.assertEqual(response.data['requirements']['percent'], 75)
        self.assertEqual(len(response.data['risk']['above_tolerable']), 1)
        self.assertIsNone(response.data['zone'])
        response = self.client.get(f'{url}?site_id={self.site.pk}&zone_id={self.cell.pk}', **self.header)
        self.assertEqual(response.data['zone'], 'Cell')
        self.assertEqual(response.data['security_levels'][1]['achieved'], 1)
        for query in (f'site_id={self.site.pk}&zone_id=0', f'site_id={self.site.pk}&zone_id=x', ''):
            response = self.client.get(f'{url}?{query}', **self.header)
            self.assertHttpStatus(response, status.HTTP_400_BAD_REQUEST)
