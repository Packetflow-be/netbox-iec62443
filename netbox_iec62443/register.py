"""
The zone and conduit register of a site: the audit deliverable. One structure, rendered as HTML (printable),
CSV (one file per table) and JSON (REST API).
"""
import csv
import io

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
FLOW_COLUMNS = (
    'flow', 'conduit', 'from_zone', 'to_zone', 'protocol', 'ports', 'access', 'remote_access', 'path', 'allowed',
    'decided_by', 'decided_on', 'review_by', 'expires', 'first_seen', 'last_seen',
)


def _yes(value):
    return 'yes' if value else 'no'


def _date(value):
    return value.isoformat() if value else ''


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
            'ports': ', '.join(f.port_mappings), 'access': ', '.join(f.access),
            'remote_access': _yes(f.remote_access), 'path': ' -> '.join(str(h.hop) for h in f.hops.all()),
            'allowed': f.get_allowed_display() + (' (expired)' if f.is_expired else ''),
            'decided_by': str(f.decided_by or ''), 'decided_on': _date(f.decided_on),
            'review_by': _date(f.review_by), 'expires': _date(f.expires), 'first_seen': _date(f.first_seen),
            'last_seen': _date(f.last_seen),
            '_object': f,
        })
    findings = run_checks(site=site, user=user)
    return {
        'site': site,
        'generated': timezone.now(),
        'version': __version__,
        'zones': zone_rows,
        'conduits': conduit_rows,
        'flows': flow_rows,
        'findings': findings,
        'summary': summary(findings),
    }


def register_csv(register, table):
    """One table of the register ('zones', 'conduits' or 'flows') as CSV text."""
    columns = {'zones': ZONE_COLUMNS, 'conduits': CONDUIT_COLUMNS, 'flows': FLOW_COLUMNS}[table]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns, extrasaction='ignore')
    writer.writeheader()
    for row in register[table]:
        writer.writerow(row)
    return out.getvalue()


def register_json(register):
    """The register without model objects, for the REST API."""
    def clean(rows):
        return [{k: v for k, v in row.items() if not k.startswith('_')} for row in rows]
    return {
        'generated': register['generated'].isoformat(),
        'plugin_version': register['version'],
        'zones': clean(register['zones']),
        'conduits': clean(register['conduits']),
        'flows': clean(register['flows']),
        'findings': [{'check': f.check, 'severity': f.severity, 'object': str(f.obj), 'message': f.message}
                     for f in register['findings']],
    }


__all__ = ('build_register', 'register_csv', 'register_json')
