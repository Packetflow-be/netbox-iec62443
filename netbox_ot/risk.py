"""
Visual aids for a risk assessment: the organisation's risk matrix (likelihood x impact gives the risk level)
with where the unmitigated and the residual risk sit and where the tolerable risk ends, and the steps of an
IEC 62443-3-2 assessment with the one this assessment is at and what is still missing.

The matrix is the organisation's own: the `risk_matrix` plugin setting replaces the default 5 x 5 below. The
plugin ships no text of the standard; the steps are named in our own words with the ZCR identifiers.
"""
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from .choices import RiskAssessmentKindChoices, RiskAssessmentStatusChoices, RiskLevelChoices

# A common 5 x 5 matrix. `levels` has one row per likelihood, lowest first; each row has one risk level per
# impact, lowest first.
DEFAULT_MATRIX = {
    'likelihood': ['Remote', 'Unlikely', 'Possible', 'Likely', 'Almost certain'],
    'impact': ['Trivial', 'Minor', 'Moderate', 'Major', 'Severe'],
    'levels': [
        ['low', 'low', 'low', 'medium', 'medium'],
        ['low', 'low', 'medium', 'medium', 'high'],
        ['low', 'medium', 'medium', 'high', 'high'],
        ['medium', 'medium', 'high', 'high', 'critical'],
        ['medium', 'high', 'high', 'critical', 'critical'],
    ],
}
MAX_SIZE = 9
ORDER = RiskLevelChoices.values()
LEVEL_LABELS = {
    'low': gettext_lazy('Low'), 'medium': gettext_lazy('Medium'), 'high': gettext_lazy('High'),
    'critical': gettext_lazy('Critical'),
}


def check_matrix(matrix):
    """Raise ImproperlyConfigured when a `risk_matrix` setting is not a usable matrix."""
    try:
        likelihood, impact, levels = matrix['likelihood'], matrix['impact'], matrix['levels']
        usable = (
            1 < len(likelihood) <= MAX_SIZE and 1 < len(impact) <= MAX_SIZE and len(levels) == len(likelihood)
            and all(len(row) == len(impact) and all(level in ORDER for level in row) for row in levels)
        )
    except (KeyError, TypeError):
        usable = False
    if not usable:
        raise ImproperlyConfigured(
            'netbox_ot: the risk_matrix setting needs "likelihood" and "impact" (2 to 9 labels each, lowest first) '
            'and "levels": one row per likelihood with one of low, medium, high, critical per impact.'
        )


def get_matrix():
    return settings.PLUGINS_CONFIG.get('netbox_ot', {}).get('risk_matrix') or DEFAULT_MATRIX


def scale_choices(axis):
    """Form choices for 'likelihood' or 'impact': 1 (lowest) upwards, with the organisation's labels."""
    return [(n, f'{n} - {label}') for n, label in enumerate(get_matrix()[axis], start=1)]


def matrix_level(likelihood, impact):
    """The risk level the matrix gives, or None when either is missing or off the matrix."""
    levels = get_matrix()['levels']
    if not likelihood or not impact or likelihood > len(levels) or impact > len(levels[0]):
        return None
    return levels[likelihood - 1][impact - 1]


def _above(level, tolerable):
    return bool(level and tolerable) and ORDER.index(level) > ORDER.index(tolerable)


def matrix_view(assessment):
    """
    The matrix for the template: rows from the highest likelihood down, each cell with its level, the marks of
    this assessment in it (U unmitigated, R residual) and whether the tolerable risk ends at its top or right edge.
    """
    matrix = get_matrix()
    levels, tolerable = matrix['levels'], assessment.tolerable_risk
    marks = {
        (assessment.unmitigated_likelihood, assessment.unmitigated_impact): 'U',
        (assessment.residual_likelihood, assessment.residual_impact): 'R',
    }
    both = (assessment.unmitigated_likelihood, assessment.unmitigated_impact) == \
        (assessment.residual_likelihood, assessment.residual_impact)

    def cell(i, j):
        level = levels[i][j]
        mark = marks.get((i + 1, j + 1))
        up = levels[i + 1][j] if i + 1 < len(levels) else None
        right = levels[i][j + 1] if j + 1 < len(levels[i]) else None
        inside = bool(tolerable) and not _above(level, tolerable)
        return {
            'level': level,
            'label': LEVEL_LABELS[level],
            'marks': (['U', 'R'] if both else [mark]) if mark else [],
            'above': _above(level, tolerable),
            'edge_top': inside and _above(up, tolerable),
            'edge_right': inside and _above(right, tolerable),
        }

    rows = [
        {'value': i + 1, 'label': matrix['likelihood'][i], 'cells': [cell(i, j) for j in range(len(levels[i]))]}
        for i in reversed(range(len(levels)))
    ]
    # Without likelihood and impact the levels still show on a plain scale
    scale = [
        {
            'level': level,
            'label': LEVEL_LABELS[level],
            'marks': [m for m, value in (('U', assessment.unmitigated_risk), ('R', assessment.residual_risk),
                                         ('T', tolerable)) if value == level],
            'above': _above(level, tolerable),
        } for level in ORDER
    ]
    return {
        'rows': rows,
        'impact': list(enumerate(matrix['impact'], start=1)),
        'placed': any(key[0] and key[1] for key in marks),
        'scale': scale,
        'tolerable': LEVEL_LABELS.get(tolerable),
        'method': assessment.method,
        'default': matrix is DEFAULT_MATRIX,
    }


def steps(assessment, others=()):
    """
    The steps of an IEC 62443-3-2 assessment as dicts (key, title, state, note, missing): state is done, current,
    todo, skipped or attention. `others` are the other assessments of the same zone or conduit; an initial
    assessment among them counts for the first step of a detailed one.
    """
    a = assessment
    initial = a.kind == RiskAssessmentKindChoices.INITIAL
    earlier = next((o for o in others if o.kind == RiskAssessmentKindChoices.INITIAL), None)
    later = next((o for o in others if o.kind == RiskAssessmentKindChoices.DETAILED), None)
    exceeds = _above(a.unmitigated_risk, a.tolerable_risk)
    known = bool(a.unmitigated_risk and a.tolerable_risk)
    result = []

    def step(key, title, done, missing=(), note='', skipped=False, attention=False):
        result.append({
            'key': key, 'title': title, 'note': note, 'missing': [m for m in missing if m],
            'state': 'skipped' if skipped else 'attention' if attention else 'done' if done else 'todo',
        })

    # 1. Initial assessment (ZCR 2): the worst case, without countermeasures
    if initial:
        step('initial', _('Initial assessment (ZCR 2)'), bool(a.unmitigated_risk),
             [not a.unmitigated_risk and _('the unmitigated (worst case) risk')])
    else:
        step('initial', _('Initial assessment (ZCR 2)'), bool(earlier or a.unmitigated_risk),
             [not (earlier or a.unmitigated_risk) and _('an initial assessment, or the unmitigated risk here')],
             note=_('Recorded as {assessment}').format(assessment=earlier) if earlier else '')
    # 2. Does the unmitigated risk exceed the tolerable risk?
    step('compare', _('Above tolerable risk?'), known,
         [not a.tolerable_risk and _('the tolerable risk'),
          not a.unmitigated_risk and _('the unmitigated risk')],
         note=(_('Yes: a detailed assessment is needed') if exceeds else _('No: the zone can be accepted as it is'))
         if known else '')
    stop = known and not exceeds   # nothing to treat: straight to approval
    # 3. Detailed assessment (ZCR 5)
    if initial:
        step('detailed', _('Detailed assessment (ZCR 5)'), bool(later),
             [not later and _('a detailed assessment of this zone or conduit')], skipped=stop,
             note=_('Recorded as {assessment}').format(assessment=later) if later else '')
    else:
        missing = [not a.threats and _('threats'), not a.vulnerabilities and _('vulnerabilities'),
                   not a.consequences and _('consequences'),
                   not (a.unmitigated_likelihood and a.unmitigated_impact) and _('likelihood and impact (unmitigated)')]
        step('detailed', _('Detailed assessment (ZCR 5)'), not any(missing[:3]), missing, skipped=stop)
    # 4. Countermeasures
    step('countermeasures', _('Countermeasures'), bool(a.countermeasures),
         [not a.countermeasures and _('the countermeasures')], skipped=stop or initial and not a.countermeasures)
    # 5. Residual risk against tolerable risk
    over = a.residual_above_tolerable
    step('residual', _('Residual risk within tolerable?'), bool(a.residual_risk) and not over,
         [not a.residual_risk and _('the residual risk'),
          over and _('more countermeasures, or an explicit acceptance of the residual risk')],
         skipped=stop or initial and not a.residual_risk, attention=over,
         note=_('No: residual risk is above tolerable') if over else _('Yes') if a.residual_risk else '')
    # 6. Approval by the asset owner
    approved = a.status == RiskAssessmentStatusChoices.APPROVED
    step('approval', _('Approval'), approved and bool(a.approved_by_id),
         [not approved and _('approval (status Approved, with a date)'),
          not a.approved_by_id and _('who approved it'), not a.next_review and _('a next review date')])
    # The step it is at: the first that is not done; a step needing attention stays as it is
    for item in result:
        if item['state'] == 'attention':
            break
        if item['state'] == 'todo':
            item['state'] = 'current'
            break
    return result


def current_step(assessment):
    """The title of the step the assessment is at (by its own fields), or '' when all are done."""
    for item in steps(assessment):
        if item['state'] in ('current', 'attention'):
            return item['title']
    return ''
