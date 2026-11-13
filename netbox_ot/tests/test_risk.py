import datetime

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.test import override_settings
from django.urls import reverse

from dcim.models import Site
from tenancy.models import Contact
from utilities.testing import TestCase

from netbox_ot import risk
from netbox_ot.forms import RiskAssessmentForm
from netbox_ot.models import RiskAssessment, Zone

TODAY = datetime.date(2026, 6, 1)
THREE = {
    'likelihood': ['Rare', 'Sometimes', 'Often'],
    'impact': ['Small', 'Large'],
    'levels': [['low', 'medium'], ['low', 'high'], ['medium', 'critical']],
}


class RiskTestBase(TestCase):
    user_permissions = ('netbox_ot.view_riskassessment', 'netbox_ot.add_riskassessment', 'netbox_ot.view_zone')

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(name='Site 1', slug='site-1')
        cls.zone = Zone.objects.create(name='Cell', slug='cell', site=cls.site, purdue_level='1')
        cls.owner = Contact.objects.create(name='Plant manager')

    def assessment(self, **kwargs):
        return RiskAssessment(zone=self.zone, assessed_on=TODAY, **kwargs)


class RiskMatrixTest(RiskTestBase):

    def test_matrix_gives_the_level(self):
        self.assertEqual(risk.matrix_level(4, 3), 'high')
        self.assertEqual(risk.matrix_level(1, 1), 'low')
        self.assertEqual(risk.matrix_level(5, 5), 'critical')
        self.assertIsNone(risk.matrix_level(None, 3))
        self.assertIsNone(risk.matrix_level(6, 1))

    def test_level_is_taken_from_the_matrix(self):
        a = self.assessment(unmitigated_likelihood=4, unmitigated_impact=3, residual_likelihood=2, residual_impact=3)
        a.full_clean()
        self.assertEqual((a.unmitigated_risk, a.residual_risk), ('high', 'medium'))
        self.assertEqual(a.unmitigated_place, '4 - Likely, 3 - Moderate')

    def test_validation(self):
        with self.assertRaisesMessage(ValidationError, 'go together'):
            self.assessment(unmitigated_likelihood=4).full_clean()
        with self.assertRaisesMessage(ValidationError, 'The risk matrix gives High'):
            self.assessment(unmitigated_likelihood=4, unmitigated_impact=3, unmitigated_risk='low').full_clean()
        with self.assertRaisesMessage(ValidationError, 'not on the risk matrix'):
            self.assessment(residual_likelihood=6, residual_impact=1).full_clean()
        # Without likelihood and impact an assessment is as valid as before
        self.assessment(unmitigated_risk='high', residual_risk='low').full_clean()

    def test_view_of_the_matrix(self):
        a = self.assessment(unmitigated_likelihood=4, unmitigated_impact=3, residual_likelihood=2, residual_impact=3,
                            tolerable_risk='medium', unmitigated_risk='high', residual_risk='medium')
        view = risk.matrix_view(a)
        self.assertTrue(view['placed'])
        self.assertEqual([row['value'] for row in view['rows']], [5, 4, 3, 2, 1])
        cells = {(row['value'], j + 1): cell for row in view['rows'] for j, cell in enumerate(row['cells'])}
        self.assertEqual(cells[(4, 3)]['marks'], ['U'])
        self.assertEqual(cells[(2, 3)]['marks'], ['R'])
        self.assertTrue(cells[(4, 3)]['above'])
        # Medium at (3, 3) is tolerable, high above it and to its right is not: the line runs along both edges
        self.assertTrue(cells[(3, 3)]['edge_top'] and cells[(3, 3)]['edge_right'])
        self.assertFalse(cells[(1, 1)]['edge_top'] or cells[(1, 1)]['edge_right'])
        # Same place for both
        a.residual_likelihood, a.residual_impact = 4, 3
        self.assertEqual(risk.matrix_view(a)['rows'][1]['cells'][2]['marks'], ['U', 'R'])

    def test_scale_without_likelihood_and_impact(self):
        view = risk.matrix_view(self.assessment(unmitigated_risk='high', residual_risk='medium',
                                                tolerable_risk='medium'))
        self.assertFalse(view['placed'])
        self.assertEqual([cell['marks'] for cell in view['scale']], [[], ['R', 'T'], ['U'], []])

    @override_settings(PLUGINS_CONFIG={'netbox_ot': {'risk_matrix': THREE}})
    def test_own_matrix(self):
        self.assertEqual(risk.matrix_level(3, 2), 'critical')
        self.assertEqual(risk.scale_choices('likelihood'), [(1, '1 - Rare'), (2, '2 - Sometimes'), (3, '3 - Often')])
        with self.assertRaisesMessage(ValidationError, 'not on the risk matrix'):
            self.assessment(unmitigated_likelihood=2, unmitigated_impact=3).full_clean()
        view = risk.matrix_view(self.assessment(unmitigated_likelihood=3, unmitigated_impact=2))
        self.assertEqual((len(view['rows']), len(view['impact'])), (3, 2))
        form = RiskAssessmentForm()
        self.assertEqual(len(form.fields['unmitigated_impact'].choices), 3)  # blank and two impacts

    def test_setting_is_checked(self):
        risk.check_matrix(THREE)
        risk.check_matrix(risk.DEFAULT_MATRIX)
        for broken in ({}, {**THREE, 'levels': THREE['levels'][:2]}, {**THREE, 'impact': ['One']},
                       {**THREE, 'levels': [['low', 'severe']] * 3}, 'matrix'):
            with self.assertRaises(ImproperlyConfigured):
                risk.check_matrix(broken)


class RiskStepsTest(RiskTestBase):

    def _states(self, assessment, others=()):
        return {s['key']: s['state'] for s in risk.steps(assessment, others)}

    def test_new_initial_assessment(self):
        a = self.assessment(kind='initial')
        self.assertEqual(self._states(a)['initial'], 'current')
        self.assertEqual(a.current_step, 'Initial assessment (ZCR 2)')

    def test_initial_within_tolerable_goes_to_approval(self):
        a = self.assessment(kind='initial', unmitigated_risk='low', tolerable_risk='medium')
        self.assertEqual(self._states(a), {
            'initial': 'done', 'compare': 'done', 'detailed': 'skipped', 'countermeasures': 'skipped',
            'residual': 'skipped', 'approval': 'current'})

    def test_initial_above_tolerable_needs_a_detailed_one(self):
        a = self.assessment(kind='initial', unmitigated_risk='high', tolerable_risk='medium')
        self.assertEqual(self._states(a)['detailed'], 'current')
        detailed = self.assessment(kind='detailed')
        self.assertEqual(self._states(a, [detailed])['detailed'], 'done')

    def test_detailed_assessment(self):
        a = self.assessment(unmitigated_risk='high', tolerable_risk='medium', threats='t', vulnerabilities='v',
                            consequences='c')
        states = self._states(a)
        self.assertEqual((states['detailed'], states['countermeasures']), ('done', 'current'))
        missing = {s['key']: s['missing'] for s in risk.steps(a)}
        self.assertEqual(missing['detailed'], ['likelihood and impact (unmitigated)'])
        a.countermeasures, a.residual_risk = 'firewall', 'high'
        self.assertEqual(self._states(a)['residual'], 'attention')
        self.assertEqual(a.current_step, 'Residual risk within tolerable?')
        self.assertEqual(self._states(a)['approval'], 'todo')
        a.residual_risk = 'medium'
        self.assertEqual(self._states(a)['approval'], 'current')
        a.status, a.approved_on, a.approved_by, a.next_review = 'approved', TODAY, self.owner, TODAY
        self.assertEqual(set(self._states(a).values()), {'done'})
        self.assertEqual(a.current_step, '')


class RiskPagesTest(RiskTestBase):

    @override_settings(EXEMPT_VIEW_PERMISSIONS=[])
    def test_detail_page(self):
        a = self.assessment(kind='initial', unmitigated_likelihood=3, unmitigated_impact=4, tolerable_risk='medium',
                            method='Company matrix')
        a.full_clean()
        a.save()
        response = self.client.get(a.get_absolute_url())
        self.assertHttpStatus(response, 200)
        self.assertContains(response, 'ot-risk-mark m-U')
        self.assertContains(response, 'r-edge-top')
        self.assertContains(response, 'Start the detailed assessment')
        self.assertContains(response, f'zone={self.zone.pk}&amp;kind=detailed')
        self.assertContains(response, 'Company matrix')
        # An assessment from before the matrix: the plain scale
        old = self.assessment(unmitigated_risk='high')
        old.save()
        response = self.client.get(old.get_absolute_url())
        self.assertHttpStatus(response, 200)
        self.assertContains(response, 'Record the likelihood and impact')

    @override_settings(EXEMPT_VIEW_PERMISSIONS=[])
    def test_list_shows_the_step(self):
        self.assessment(unmitigated_risk='high', tolerable_risk='medium').save()
        response = self.client.get(reverse('plugins:netbox_ot:riskassessment_list'))
        self.assertHttpStatus(response, 200)
        self.assertContains(response, 'Detailed assessment (ZCR 5)')

    def test_form_takes_the_level_from_the_matrix(self):
        form = RiskAssessmentForm(data={
            'zone': self.zone.pk, 'kind': 'detailed', 'status': 'draft', 'assessed_on': '2026-06-01',
            'unmitigated_likelihood': '5', 'unmitigated_impact': '5',
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().unmitigated_risk, 'critical')
