"""
The OT overview of a site: where it stands, at a glance. Security levels per foundational requirement (target
against achieved, as a radar chart and a table sorted by gap), requirement statuses per foundational requirement,
the risk assessments (before and after countermeasures, against the tolerable risk) and the consistency checks.

One structure, rendered as a page (printable) and as JSON (REST API). Nothing here is stored: it is all derived
from the zones, conduits, risk assessments and requirement statuses.
"""
import math
from urllib.parse import urlencode

from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _

from . import __version__, exposure, sl
from .checks import SEVERITIES, run_checks
from .choices import (
    FoundationalRequirementChoices,
    RequirementStatusChoices,
    RiskAssessmentStatusChoices,
    RiskLevelChoices,
    ZoneTypeChoices,
)
from .models import Conduit, Flow, Zone
from .register import _latest, _requirement_rows

# Rows of the security level table, most urgent first
STATE_ORDER = ('gap', 'no-achieved', 'no-target', 'met')
# Status columns of the requirements table; '' is an applicable requirement without a status yet
REQUIREMENT_STATES = (
    RequirementStatusChoices.MET, RequirementStatusChoices.COMPENSATED, RequirementStatusChoices.NOT_APPLICABLE,
    RequirementStatusChoices.NOT_MET, '',
)
LIST_LIMIT = 12


def _fr_labels():
    return [str(label) for _value, label in FoundationalRequirementChoices.CHOICES]


def _level_row(kind, obj):
    target, achieved = obj.sl_target, obj.sl_achieved
    cells = [{
        'target': target[i] if target else None,
        'achieved': achieved[i] if achieved else None,
        'gap': bool(target and achieved and achieved[i] < target[i]),
    } for i in range(sl.FR_COUNT)]
    if not target:
        state, gap = 'no-target', None
    elif not achieved:
        state, gap = 'no-achieved', None
    else:
        gap = sum(max(0, target[i] - achieved[i]) for i in range(sl.FR_COUNT))
        state = 'gap' if gap else 'met'
    return {
        'kind': kind, 'name': obj.name, 'state': state, 'gap': gap, 'cells': cells,
        'below': sl.below(achieved, target), 'sl_target': sl.display(target), 'sl_achieved': sl.display(achieved),
        'object': obj,
    }


def _weakest(measured, i):
    """
    The zone that sets the site's level in foundational requirement `i`: the one furthest below its target, then
    the one with the lowest achieved level. Security levels are whole numbers and an attacker picks the weakest
    zone, so the site is never shown as an average.
    """
    return min(measured, key=lambda z: (z.sl_achieved[i] - z.sl_target[i], z.sl_achieved[i], z.name))


def _axes(zones, focus=None):
    """
    Per foundational requirement: the target and achieved level to draw. Of one zone (`focus`), or of the weakest
    zone in that requirement among the zones that have both a target and an achieved level (`zone` names it), with
    how many of them are below target.
    """
    labels = _fr_labels()
    weakest = [None] * sl.FR_COUNT
    if focus is not None:
        measured = [focus] if focus.sl_target else []
        target = focus.sl_target
        achieved = focus.sl_achieved
    else:
        measured = [z for z in zones if z.sl_target and z.sl_achieved]
        target = achieved = None
        if measured:
            weakest = [_weakest(measured, i) for i in range(sl.FR_COUNT)]
            target = [weakest[i].sl_target[i] for i in range(sl.FR_COUNT)]
            achieved = [weakest[i].sl_achieved[i] for i in range(sl.FR_COUNT)]
    axes = []
    for i in range(sl.FR_COUNT):
        below = sum(1 for z in measured if z.sl_achieved and z.sl_achieved[i] < z.sl_target[i])
        axes.append({
            'fr': sl.FR_SHORT[i], 'label': labels[i],
            'target': target[i] if target else None, 'achieved': achieved[i] if achieved else None,
            'zone': weakest[i].name if weakest[i] is not None else None,
            'below': below, 'measured': len(measured),
        })
    return axes


def _weakest_zones(axes):
    """[(zone name, [FRs])]: which zone sets the site's level in which foundational requirements."""
    frs = {}
    for a in axes:
        if a.get('zone'):
            frs.setdefault(a['zone'], []).append(a['fr'])
    return sorted(frs.items(), key=lambda item: (-len(item[1]), item[0]))


def _furthest(axes):
    """The foundational requirement furthest below its target, or None when none is below."""
    def shortfall(a):
        return (a['target'] or 0) - (a['achieved'] or 0) if a['achieved'] is not None else 0
    worst = max(axes, key=lambda a: (shortfall(a), a['below']))
    return worst if shortfall(worst) > 0 else None


def _requirements(rows):
    """Requirement statuses counted per foundational requirement, and in total."""
    labels = _fr_labels()
    per_fr = [{'fr': sl.FR_SHORT[i], 'label': labels[i], 'counts': {s: 0 for s in REQUIREMENT_STATES}}
              for i in range(sl.FR_COUNT)]
    for row in rows:
        per_fr[sl.FR_SHORT.index(row['foundational_requirement'])]['counts'][row['status_code']] += 1
    total = {s: 0 for s in REQUIREMENT_STATES}
    for fr in per_fr:
        counts = fr['counts']
        fr['total'] = sum(counts.values())
        fr['satisfied'] = sum(counts[s] for s in RequirementStatusChoices.SATISFIED)
        fr['percent'] = round(100 * fr['satisfied'] / fr['total']) if fr['total'] else None
        # In the order of REQUIREMENT_STATES, for the page
        fr['cells'] = [counts[s] for s in REQUIREMENT_STATES]
        fr['bar'] = [
            {'state': s or 'open', 'count': counts[s], 'width': round(100 * counts[s] / fr['total'], 1)}
            for s in REQUIREMENT_STATES if counts[s]
        ]
        for s in REQUIREMENT_STATES:
            total[s] += counts[s]
    count = sum(total.values())
    satisfied = sum(total[s] for s in RequirementStatusChoices.SATISFIED)
    return {
        'per_fr': per_fr, 'total': count, 'satisfied': satisfied,
        'percent': round(100 * satisfied / count) if count else None,
        'not_met': total[RequirementStatusChoices.NOT_MET], 'open': total[''],
    }


def _risk(subjects):
    """
    The latest approved risk assessment of every zone and conduit: how many sit at each risk level before
    (unmitigated) and after (residual) countermeasures, which are above the tolerable risk and which have none.
    """
    levels = RiskLevelChoices.values()
    labels = dict(RiskLevelChoices.CHOICES)
    unmitigated = {level: 0 for level in levels}
    residual = {level: 0 for level in levels}
    above, without, assessed = [], [], 0
    for kind, obj in subjects:
        ra = _latest(obj.risk_assessments.all())
        if ra is None:
            without.append({'kind': kind, 'name': obj.name, 'object': obj})
            continue
        assessed += 1
        if ra.unmitigated_risk:
            unmitigated[ra.unmitigated_risk] += 1
        if ra.residual_risk:
            residual[ra.residual_risk] += 1
        if ra.residual_above_tolerable:
            above.append({
                'kind': kind, 'name': obj.name, 'residual_risk': str(labels[ra.residual_risk]),
                'tolerable_risk': str(labels[ra.tolerable_risk]),
                'residual_color': RiskLevelChoices.colors.get(ra.residual_risk),
                'object': obj, 'assessment': ra,
            })
    most = max([*unmitigated.values(), *residual.values(), 1])
    rows = [{
        'level': level, 'label': str(labels[level]), 'color': RiskLevelChoices.colors.get(level),
        'unmitigated': unmitigated[level], 'residual': residual[level],
        'unmitigated_width': round(100 * unmitigated[level] / most, 1),
        'residual_width': round(100 * residual[level] / most, 1),
    } for level in reversed(levels)]
    return {
        'levels': rows, 'assessed': assessed, 'subjects': len(subjects), 'above_tolerable': above,
        'without_assessment': without, 'without_shown': without[:LIST_LIMIT],
        'without_more': max(0, len(without) - LIST_LIMIT),
    }


def _list_url(model, **params):
    return reverse(f'plugins:netbox_ot:{model}_list') + '?' + urlencode(params)


def _exposure(site, flows, zones):
    """
    What reaches the controllers, from what the import already knows: the flows into control zones (level 0-1 or
    safety), how many nobody decided on yet although they change the controllers, are remote access or come from
    outside, and the remote and outside paths among them. Needs no levels or assessments, so it is there from the
    first import on.
    """
    into = flows.filter(exposure.into_control())
    return {
        'control_zones': sum(1 for z in zones if exposure.is_control_zone(z)),
        'into_control': into.count(),
        'undecided': flows.filter(exposure.undecided_into_control()).count(),
        'changes': into.filter(exposure.changes()).count(),
        'remote': into.filter(remote_access=True).count(),
        'from_outside': into.filter(exposure.from_outside()).count(),
        'outside_allowed': flows.filter(exposure.outside_into_control()).count(),
        'external_zones': [z for z in zones if z.zone_type == ZoneTypeChoices.EXTERNAL],
        'undecided_url': _list_url('flow', site_id=site.pk, undecided_into_control='true'),
        'into_control_url': reverse('dcim:site_ot_accessmap', kwargs={'pk': site.pk}),
    }


def _next_steps(site, flows, own_zones, own_conduits):
    """
    What to add next, in the order that clears the most findings for the least work (the order the field reviews
    of a real capture and of a hand-built plant settled on). Each step: done or not, how many are left, where to
    do it. The first open step is the one to do now.
    """
    empty = [z for z in own_zones if not z.devices.all() and not z.virtual_machines.all()]
    undecided = flows.filter(exposure.undecided_into_control()).count()
    no_owner = [z for z in own_zones if not z.accountable_id]
    no_target = [z for z in own_zones if not z.sl_target]
    no_achieved = [z for z in own_zones if z.sl_target and not z.sl_achieved]
    no_conduit = flows.filter(conduit__isnull=True).count()
    subjects = own_zones + own_conduits
    unassessed = [s for s in subjects if not any(
        ra.status == RiskAssessmentStatusChoices.APPROVED for ra in s.risk_assessments.all())]
    steps = [
        {
            'key': 'devices', 'left': len(empty),
            'title': _('Get the devices into NetBox'),
            'todo': _('%(n)s zone(s) have no devices or VMs yet. Create them before the next import (ot_import '
                      '--unknown-import writes the files for NetBox\'s import pages), so splits and levels stick.')
            % {'n': len(empty)},
            'url': _list_url('zone', site_id=site.pk),
        },
        {
            'key': 'decide', 'left': undecided,
            'title': _('Decide the flows into control zones'),
            'todo': _('%(n)s flow(s) into a control zone change it, are remote access or come from outside, and '
                      'nobody decided yet whether they may. Select them all and set Allowed with one bulk edit.')
            % {'n': undecided},
            'url': _list_url('flow', site_id=site.pk, undecided_into_control='true'),
        },
        {
            'key': 'levels', 'left': len({z.pk for z in no_owner + no_target + no_achieved}),
            'title': _('Owner, target and achieved level per zone'),
            'todo': _('%(owner)s zone(s) without an accountable person, %(target)s without a target level (SL-T), '
                      '%(achieved)s without an achieved level (SL-A). Bulk edit sets them; the chart needs both '
                      'levels.') % {'owner': len(no_owner), 'target': len(no_target), 'achieved': len(no_achieved)},
            'url': _list_url('zone', site_id=site.pk, has_sl_target='false') if no_target else
            _list_url('zone', site_id=site.pk, has_accountable='false') if no_owner else
            _list_url('zone', site_id=site.pk, has_sl_achieved='false'),
        },
        {
            'key': 'conduits', 'left': no_conduit,
            'title': _('Conduits'),
            'todo': _('%(n)s flow(s) run outside any conduit. Add a conduit per path between zones and set the '
                      'conduit on its flows; give each conduit an owner and SL-T in the same bulk edit.')
            % {'n': no_conduit},
            'url': _list_url('flow', site_id=site.pk, has_conduit='false'),
        },
        {
            'key': 'risk', 'left': len(unassessed),
            'title': _('Risk assessments and requirement statuses'),
            'todo': _('%(n)s zone(s) and conduit(s) without an approved risk assessment.') % {'n': len(unassessed)},
            'url': _list_url('riskassessment', site_id=site.pk),
        },
    ]
    first = next((s for s in steps if s['left']), None)
    for step in steps:
        step['done'] = not step['left']
        step['now'] = step is first
    return steps


def build_overview(site, user=None, zone=None):
    """
    The overview of `site` as plain data. `zone` (a zone of the site) draws the radar chart for that zone
    instead of the weakest zone per foundational requirement.
    """
    def visible(qs):
        return qs.restrict(user, 'view') if user is not None else qs

    zones = list(visible(Zone.objects.filter(site=site)).prefetch_related(
        'risk_assessments', 'devices', 'virtual_machines'))
    conduits = visible(Conduit.objects.filter(zones__site=site) | Conduit.objects.filter(site=site)).distinct()
    conduits = list(conduits.prefetch_related('risk_assessments'))
    # External zones (a supplier, the internet) are outside the system under consideration: no levels or
    # assessments of their own, as in the checks
    own_zones = [z for z in zones if z.zone_type != ZoneTypeChoices.EXTERNAL]
    subjects = [('zone', z) for z in own_zones] + [('conduit', c) for c in conduits]
    flows = visible(Flow.objects.filter(Q(source_zone__site=site) | Q(destination_zone__site=site)))
    focus = next((z for z in zones if zone is not None and z.pk == zone.pk), None)

    level_rows = [_level_row(kind, obj) for kind, obj in subjects]
    level_rows.sort(key=lambda r: (STATE_ORDER.index(r['state']), -(r['gap'] or 0), r['kind'] != 'zone', r['name']))
    axes = _axes(own_zones, focus)
    with_target = [r for r in level_rows if r['kind'] == 'zone' and r['state'] != 'no-target']
    findings = run_checks(site=site, user=user)
    return {
        'site': site,
        'generated': timezone.now(),
        'version': __version__,
        'focus': focus,
        'axes': axes,
        'weakest': _weakest_zones(axes),
        'furthest': _furthest(axes),
        'chart': radar_svg(axes),
        'levels': level_rows,
        'exposure': _exposure(site, flows, zones),
        'next_steps': _next_steps(site, flows, own_zones, conduits),
        'zones': {
            'total': len(own_zones),
            'with_target': len(with_target),
            'at_target': sum(1 for r in with_target if r['state'] == 'met'),
            'below_target': sum(1 for r in with_target if r['state'] == 'gap'),
            'not_assessed': sum(1 for r in with_target if r['state'] == 'no-achieved'),
        },
        'requirements': _requirements(_requirement_rows(zones, conduits, visible)),
        'risk': _risk(subjects),
        'findings': {
            'total': len(findings),
            **{severity: sum(1 for f in findings if f.severity == severity) for severity in SEVERITIES},
        },
    }


def overview_json(overview):
    """The overview without model objects and without the drawing, for the REST API."""
    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()
                    if not k.startswith('_') and not isinstance(v, models.Model)}
        if isinstance(value, (list, tuple)):
            return [clean(v) for v in value]
        return value

    risk = {k: v for k, v in overview['risk'].items() if k not in ('without_shown', 'without_more')}
    requirements = dict(overview['requirements'])
    requirements['per_fr'] = [{k: v for k, v in fr.items() if k not in ('cells', 'bar')}
                              for fr in requirements['per_fr']]
    for fr in requirements['per_fr']:
        fr['counts'] = {(state or 'no-status'): n for state, n in fr['counts'].items()}
    exposure_data = {k: v for k, v in overview['exposure'].items() if not k.endswith('_url')}
    exposure_data['external_zones'] = [z.name for z in exposure_data['external_zones']]
    return {
        'generated': overview['generated'].isoformat(),
        'plugin_version': overview['version'],
        'exposure': exposure_data,
        'next_steps': [{k: str(v) if k in ('title', 'todo') else v for k, v in step.items()}
                       for step in overview['next_steps']],
        'zone': overview['focus'].name if overview['focus'] else None,
        'zones': overview['zones'],
        'security_levels': clean(overview['axes']),
        'furthest_from_target': overview['furthest']['fr'] if overview['furthest'] else None,
        'subjects': clean(overview['levels']),
        'requirements': clean(requirements),
        'risk': clean(risk),
        'findings': overview['findings'],
    }


#
# The radar chart
#

def _number(value):
    """2 for 2.0, 1.5 for 1.5, 1.67 for 1.666."""
    return f'{value:.2f}'.rstrip('0').rstrip('.')


def radar_svg(axes, size=360):
    """
    Target (outline) against achieved (filled) security level, one spoke per foundational requirement and a ring
    per level. The outer ring is the highest level drawn (at least SL 2), so a plant at SL 2 fills the chart.
    Server-rendered SVG without scripts, so it prints and works offline. Colours come from the theme.
    Returns '' when there is no target to draw.
    """
    if not any(a['target'] is not None for a in axes):
        return ''
    n = len(axes)
    highest = max(v for a in axes for v in (a['target'], a['achieved']) if v is not None)
    max_level = min(4, max(2, math.ceil(highest)))
    pad_x, pad_top, pad_bottom = 96, 44, 48
    radius = size / 2 - 24
    cx, cy = pad_x + radius, pad_top + radius
    width, height = 2 * (pad_x + radius), pad_top + 2 * radius + pad_bottom

    def point(i, value):
        angle = -math.pi / 2 + 2 * math.pi * i / n
        r = radius * value / max_level
        return cx + r * math.cos(angle), cy + r * math.sin(angle)

    def polygon(values):
        return ' '.join('{:.1f},{:.1f}'.format(*point(i, v or 0)) for i, v in enumerate(values))

    out = []
    for level in range(1, max_level + 1):
        out.append(f'<polygon class="ring" points="{polygon([level] * n)}"/>')
        x, y = point(0, level)
        out.append(f'<text class="tick" x="{x + 4:.1f}" y="{y + 11:.1f}">{level}</text>')
    for i in range(n):
        x, y = point(i, max_level)
        out.append(f'<line class="spoke" x1="{cx:.1f}" y1="{cy:.1f}" x2="{x:.1f}" y2="{y:.1f}"/>')

    achieved = [a['achieved'] for a in axes]
    if any(v is not None for v in achieved):
        out.append(f'<polygon class="achieved" points="{polygon(achieved)}"/>')
    out.append(f'<polygon class="target" points="{polygon([a["target"] for a in axes])}"/>')

    for i, a in enumerate(axes):
        gap = a['achieved'] is not None and a['target'] is not None and a['achieved'] < a['target']
        target = _number(a['target']) if a['target'] is not None else '-'
        value = _number(a['achieved']) if a['achieved'] is not None else '-'
        tip = _('%(label)s: achieved %(achieved)s, target %(target)s') % {
            'label': a['label'], 'achieved': value, 'target': target}
        if a.get('zone'):
            tip += ' ' + _('(zone %(zone)s)') % {'zone': a['zone']}
        if a['achieved'] is not None:
            x, y = point(i, a['achieved'])
            out.append(f'<circle class="dot{" gap" if gap else ""}" cx="{x:.1f}" cy="{y:.1f}" r="4.5">'
                       f'<title>{escape(tip)}</title></circle>')
        # The label outside the outer ring: the FR, and achieved / target underneath
        angle = -math.pi / 2 + 2 * math.pi * i / n
        lx = cx + (radius + 14) * math.cos(angle)
        ly = cy + (radius + 14) * math.sin(angle)
        cos = math.cos(angle)
        anchor = 'middle' if abs(cos) < 0.2 else ('start' if cos > 0 else 'end')
        if math.sin(angle) < -0.9:
            ly -= 18
        elif math.sin(angle) > 0.5:
            ly += 12
        out.append(
            f'<text class="axis" x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}">{escape(a["fr"])}'
            f'<title>{escape(tip)}</title></text>'
            f'<text class="value{" gap" if gap else ""}" x="{lx:.1f}" y="{ly + 15:.1f}" text-anchor="{anchor}">'
            f'{value} / {target}{" ▼" if gap else ""}</text>'
        )
    label = escape(_('Radar chart of achieved against target security level per foundational requirement'))
    return mark_safe(
        f'<svg class="ot-radar" viewBox="0 0 {width:.0f} {height:.0f}" role="img" aria-label="{label}" '
        f'xmlns="http://www.w3.org/2000/svg">' + ''.join(out) + '</svg>'
    )
