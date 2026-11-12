"""
The zone and conduit register of a site: the audit deliverable. One structure, rendered as HTML (printable),
CSV (one file per table) and JSON (REST API).
"""
import csv
import io
import re

from django.db import models
from django.db.models import Q
from django.utils import timezone

from . import __version__, sl
from .checks import run_checks, summary
from .customfields import get_purdue_level
from .models import Conduit, Flow, Zone

ZONE_COLUMNS = (
    'zone', 'type', 'purdue_level', 'parent', 'sl_target', 'sl_achieved', 'accountable', 'wireless',
    'temporary_devices', 'devices', 'virtual_machines', 'prefixes', 'risk_assessment', 'residual_risk',
    'tolerable_risk', 'next_review', 'description',
)
CONDUIT_COLUMNS = (
    'conduit', 'zones', 'sl_target', 'sl_achieved', 'enforced_by', 'accountable', 'flows', 'not_allowed',
    'unknown', 'allowed', 'risk_assessment', 'residual_risk', 'tolerable_risk', 'description',
)
REQUIREMENT_COLUMNS = (
    'zone', 'conduit', 'requirement', 'foundational_requirement', 'applies_from_sl', 'applies_at_sl_t', 'status',
    'countermeasure', 'evidence', 'risk_assessment', 'assessed_by', 'assessed_on',
)
FLOW_COLUMNS = (
    'flow', 'conduit', 'from_zone', 'to_zone', 'protocol', 'ports', 'connection', 'broker_zone', 'topics', 'access',
    'remote_access', 'path', 'allowed', 'decided_by', 'decided_on', 'review_by', 'expires', 'first_seen', 'last_seen',
)


def _yes(value):
    return 'yes' if value else 'no'


def _date(value):
    """ISO date, or date and time to the second."""
    if not value:
        return ''
    return value.replace(microsecond=0).isoformat() if hasattr(value, 'hour') else value.isoformat()


def _latest(ras):
    approved = [ra for ra in ras if ra.status == 'approved']
    return max(approved, key=lambda ra: (ra.assessed_on, ra.pk)) if approved else None


def _ra_columns(ra):
    if ra is None:
        return {'risk_assessment': '', 'residual_risk': '', 'tolerable_risk': '', 'next_review': ''}
    return {
        'risk_assessment': f'{ra.get_kind_display()} {ra.assessed_on}',
        'residual_risk': ra.get_residual_risk_display() if ra.residual_risk else '',
        'tolerable_risk': ra.get_tolerable_risk_display() if ra.tolerable_risk else '',
        'next_review': _date(ra.next_review),
    }


def build_register(site, user=None):
    """The register of `site` as plain data: zones, conduits, flows and the consistency check summary."""
    def visible(qs):
        return qs.restrict(user, 'view') if user is not None else qs

    zones = visible(Zone.objects.filter(site=site)).select_related('parent', 'accountable').prefetch_related(
        'devices', 'virtual_machines', 'prefixes', 'risk_assessments')
    conduits = visible(Conduit.objects.filter(zones__site=site) | Conduit.objects.filter(site=site)).distinct()
    conduits = conduits.select_related('accountable').prefetch_related(
        'zones', 'enforcing_devices', 'enforcing_virtual_machines', 'flows', 'risk_assessments')
    flows = visible(Flow.objects.filter(source_zone__site=site) | Flow.objects.filter(destination_zone__site=site))
    flows = flows.select_related('source_zone', 'destination_zone', 'conduit', 'decided_by').prefetch_related(
        'hops__device', 'hops__virtual_machine', 'hops__tunnel').order_by('source_zone__name',
                                                                         'destination_zone__name', 'name')
    zone_rows = []
    for z in zones:
        zone_rows.append({
            'zone': z.name, 'type': z.get_zone_type_display(), 'purdue_level': z.purdue_level,
            'parent': z.parent.name if z.parent else '', 'sl_target': sl.display(z.sl_target),
            'sl_achieved': sl.display(z.sl_achieved), 'accountable': str(z.accountable or ''),
            'wireless': _yes(z.wireless), 'temporary_devices': _yes(z.temporary_devices),
            'devices': ', '.join(f'{d.name} ({get_purdue_level(d) or "-"})' for d in z.devices.all()),
            'virtual_machines': ', '.join(v.name for v in z.virtual_machines.all()),
            'prefixes': ', '.join(str(p.prefix) for p in z.prefixes.all()),
            **_ra_columns(_latest(z.risk_assessments.all())),
            'description': z.description,
            '_object': z,
        })
    conduit_rows = []
    for c in conduits:
        verdicts = [f.allowed for f in c.flows.all()]
        ra = _ra_columns(_latest(c.risk_assessments.all()))
        ra.pop('next_review')
        conduit_rows.append({
            'conduit': c.name, 'zones': ', '.join(sorted(z.name for z in c.zones.all())),
            'sl_target': sl.display(c.sl_target), 'sl_achieved': sl.display(c.sl_achieved),
            'enforced_by': ', '.join([d.name for d in c.enforcing_devices.all()] +
                                     [v.name for v in c.enforcing_virtual_machines.all()]),
            'accountable': str(c.accountable or ''), 'flows': len(verdicts),
            'not_allowed': verdicts.count('no'), 'unknown': verdicts.count('unknown'),
            'allowed': verdicts.count('yes'), **ra, 'description': c.description,
            '_object': c,
        })
    flow_rows = []
    for f in flows:
        flow_rows.append({
            'flow': str(f), 'conduit': f.conduit.name if f.conduit else '', 'from_zone': f.source_zone.name,
            'to_zone': f.destination_zone.name, 'protocol': f.get_protocol_display() if f.protocol else '',
            'ports': ', '.join(f.port_mappings), 'connection': f.get_connection_display(),
            'broker_zone': f.broker_zone.name if f.broker_zone else '', 'topics': ', '.join(f.topics),
            'access': ', '.join(f.access),
            'remote_access': _yes(f.remote_access), 'path': ' -> '.join(str(h.hop) for h in f.hops.all()),
            'allowed': f.get_allowed_display() + (' (expired)' if f.is_expired else ''),
            'decided_by': str(f.decided_by or ''), 'decided_on': _date(f.decided_on),
            'review_by': _date(f.review_by), 'expires': _date(f.expires), 'first_seen': _date(f.first_seen),
            'last_seen': _date(f.last_seen),
            '_object': f,
        })
    findings = run_checks(site=site, user=user)
    requirement_rows = _requirement_rows(zones, conduits, visible)
    return {
        'site': site,
        'generated': timezone.now(),
        'version': __version__,
        'zones': zone_rows,
        'conduits': conduit_rows,
        'flows': flow_rows,
        'requirements': requirement_rows,
        'findings': findings,
        'summary': summary(findings),
    }


def _requirement_key(requirement):
    """SR 1.2 before SR 1.10, an enhancement right after its requirement."""
    return [int(n) for n in re.findall(r'\d+', requirement.identifier)]


def _requirement_rows(zones, conduits, visible):
    """
    Per zone and conduit: every requirement that applies at its SL-T (once the SL mapping is loaded), with or
    without a status, and every other requirement it has a status for.
    """
    from .models import RequirementStatus, SystemRequirement

    with_level = list(SystemRequirement.objects.filter(security_level__isnull=False))
    statuses = visible(RequirementStatus.objects.filter(Q(zone__in=zones) | Q(conduit__in=conduits))).select_related(
        'requirement', 'risk_assessment', 'assessed_by')
    by_subject = {}
    for rs in statuses:
        by_subject.setdefault(('zone', rs.zone_id) if rs.zone_id else ('conduit', rs.conduit_id), {})[
            rs.requirement_id] = rs
    rows = []
    for kind, objs in (('zone', zones), ('conduit', conduits)):
        for obj in objs:
            own = by_subject.get((kind, obj.pk), {})
            applicable = {r.pk: r for r in with_level if r.applies_at(obj.sl_target)}
            requirements = {**applicable, **{pk: rs.requirement for pk, rs in own.items()}}
            for requirement in sorted(requirements.values(), key=_requirement_key):
                rs = own.get(requirement.pk)
                rows.append({
                    'zone': obj.name if kind == 'zone' else '', 'conduit': obj.name if kind == 'conduit' else '',
                    'requirement': requirement.identifier,
                    'foundational_requirement': sl.FR_SHORT[requirement.fr_index],
                    'applies_from_sl': requirement.security_level or '',
                    'applies_at_sl_t': _yes(requirement.pk in applicable),
                    'status': rs.get_status_display() if rs else '',
                    'countermeasure': rs.countermeasure if rs else '', 'evidence': rs.evidence if rs else '',
                    'risk_assessment': str(rs.risk_assessment or '') if rs else '',
                    'assessed_by': str(rs.assessed_by or '') if rs else '',
                    'assessed_on': _date(rs.assessed_on) if rs else '',
                    'status_code': rs.status if rs else '',
                    # Model objects for the page; register_json() leaves them out
                    'status_object': rs, 'requirement_object': requirement,
                })
    return rows


def register_csv(register, table):
    """One table of the register ('zones', 'conduits', 'flows' or 'requirements') as CSV text."""
    columns = {'zones': ZONE_COLUMNS, 'conduits': CONDUIT_COLUMNS, 'flows': FLOW_COLUMNS,
               'requirements': REQUIREMENT_COLUMNS}[table]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns, extrasaction='ignore')
    writer.writeheader()
    for row in register[table]:
        writer.writerow(row)
    return out.getvalue()


def register_json(register):
    """The register without model objects, for the REST API."""
    def clean(rows):
        return [{k: v for k, v in row.items() if not k.startswith('_') and not isinstance(v, models.Model)}
                for row in rows]
    return {
        'generated': register['generated'].isoformat(),
        'plugin_version': register['version'],
        'zones': clean(register['zones']),
        'conduits': clean(register['conduits']),
        'flows': clean(register['flows']),
        'requirements': clean(register['requirements']),
        'findings': [{'check': f.check, 'severity': f.severity, 'object': str(f.obj), 'message': f.message}
                     for f in register['findings']],
    }


__all__ = ('build_register', 'register_csv', 'register_json')
