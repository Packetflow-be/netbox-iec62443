"""
Consistency checks: what in the zone and conduit model contradicts itself, or is missing for an audit.
Each check has a stable id (for filters and CI) and a severity:

  error    the model says something that cannot be right (an address in another zone's prefix, a member below
           its zone's level, expired access still marked allowed, residual risk above tolerable)
  warning  probably wrong or risky (an asset in no zone, a flow outside any conduit, an SL gap)
  info     not wrong, but missing for an audit (no SL-T, no accountable person, no risk assessment)

Checks only read; they never change anything.
"""
import datetime
from collections import defaultdict
from dataclasses import dataclass

from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from . import lifecycle, sl
from .choices import AccessChoices, ConnectionChoices, FlowAllowedChoices, RiskAssessmentStatusChoices, ZoneTypeChoices
from .customfields import get_purdue_level, get_sl_capability
from .models import Conduit, Flow, RequirementStatus, RiskAssessment, SystemRequirement, Zone, stale_after_days
from .requirements import open_requirements

ERROR, WARNING, INFO = 'error', 'warning', 'info'
SEVERITIES = (ERROR, WARNING, INFO)
SEVERITY_COLORS = {ERROR: 'red', WARNING: 'orange', INFO: 'blue'}


@dataclass
class Check:
    id: str
    title: str
    severity: str
    func: object


@dataclass
class Finding:
    check: str
    severity: str
    obj: object
    message: str

    @property
    def title(self):
        return CHECKS[self.check].title

    @property
    def color(self):
        return SEVERITY_COLORS[self.severity]


CHECKS = {}


def check(check_id, title, severity):
    def register(func):
        CHECKS[check_id] = Check(check_id, title, severity, func)
        return func
    return register


class Scope:
    """The zones, conduits and flows of one site (or of all sites), limited to what `user` may view."""

    def __init__(self, site=None, user=None):
        def visible(qs):
            return qs.restrict(user, 'view') if user is not None else qs

        zones = visible(Zone.objects.all())
        conduits = visible(Conduit.objects.all())
        flows = visible(Flow.objects.all())
        if site is not None:
            zones = zones.filter(site=site)
            conduits = conduits.filter(Q(site=site) | Q(zones__site=site)).distinct()
            flows = flows.filter(Q(source_zone__site=site) | Q(destination_zone__site=site))
        self.site, self.user = site, user
        self.zones = list(zones.select_related('parent', 'site').prefetch_related(
            'devices__primary_ip4', 'devices__device_type', 'virtual_machines__primary_ip4', 'prefixes',
        ))
        self.conduits = list(conduits.prefetch_related('zones', 'enforcing_devices', 'enforcing_virtual_machines'))
        self.flows = flows.select_related('source_zone', 'destination_zone')
        self.visible = visible

    def end_of_support(self):
        """{device pk: EndOfSupport} for the devices in the zones in scope (netbox-lifecycle; empty without it)."""
        if not hasattr(self, '_end_of_support'):
            self._end_of_support = lifecycle.end_of_support(
                {d.pk: d for z in self.zones for d in z.devices.all()}.values())
        return self._end_of_support

    def members(self, zone):
        return list(zone.devices.all()) + list(zone.virtual_machines.all())

    def related(self, a, b):
        """True when the zones are the same, or one is a sub-zone (at any depth) of the other."""
        return a.pk == b.pk or b.pk in self.ancestors(a) or a.pk in self.ancestors(b)

    def ancestors(self, zone):
        result, seen = set(), set()
        while zone.parent_id and zone.parent_id not in seen:
            seen.add(zone.parent_id)
            result.add(zone.parent_id)
            zone = zone.parent
        return result

    def latest_assessments(self):
        """The latest approved risk assessment per zone and per conduit in scope."""
        qs = self.visible(RiskAssessment.objects.filter(status=RiskAssessmentStatusChoices.APPROVED)).filter(
            Q(zone__in=self.zones) | Q(conduit__in=self.conduits)
        ).order_by('-assessed_on', '-pk')
        latest = {}
        for ra in qs.select_related('zone', 'conduit'):
            latest.setdefault(('zone', ra.zone_id) if ra.zone_id else ('conduit', ra.conduit_id), ra)
        return latest


    def requirement_statuses(self):
        """
        (requirements with a loaded security level, {('zone' | 'conduit', pk): {requirement pk: status}}) for the
        zones and conduits in scope. Empty requirements when nobody has loaded the SL mapping.
        """
        requirements = list(SystemRequirement.objects.filter(security_level__isnull=False))
        statuses = defaultdict(dict)
        if requirements:
            qs = self.visible(RequirementStatus.objects.filter(
                Q(zone__in=self.zones) | Q(conduit__in=self.conduits)
            ))
            for rs in qs:
                key = ('zone', rs.zone_id) if rs.zone_id else ('conduit', rs.conduit_id)
                statuses[key][rs.requirement_id] = rs
        return requirements, statuses


def _identifiers(requirements, limit=6):
    names = [str(r) for r in requirements]
    return ', '.join(names[:limit]) + (f' (+{len(names) - limit})' if len(names) > limit else '')


def _level(value):
    try:
        return float(value) if value not in (None, '') else None
    except (TypeError, ValueError):
        return None


#
# Zones and their members
#

@check('address-in-other-zone', _("Address in another zone's prefix"), ERROR)
def address_in_other_zone(scope):
    nets = [(p.prefix, p.vrf_id, z) for z in scope.zones for p in z.prefixes.all()]
    for zone in scope.zones:
        for asset in scope.members(zone):
            ip = asset.primary_ip4
            if ip is None:
                continue
            holding = [(net, owner) for net, vrf_id, owner in nets if vrf_id == ip.vrf_id and ip.address.ip in net]
            if not holding:
                continue
            longest = max(net.prefixlen for net, _owner in holding)
            owners = [owner for net, owner in holding if net.prefixlen == longest]
            if not any(scope.related(zone, owner) for owner in owners):
                net = next(net for net, _owner in holding if net.prefixlen == longest)
                yield asset, _('{asset} ({ip}) is in zone {zone}, but its address is in prefix {net} of zone '
                               '{owner}').format(asset=asset, ip=ip.address.ip, zone=zone, net=net,
                                                 owner=', '.join(str(o) for o in owners))


@check('asset-below-zone-level', _('Asset below its zone\'s Purdue level'), ERROR)
def asset_below_zone_level(scope):
    for zone in scope.zones:
        zone_level = _level(zone.purdue_level)
        if zone_level is None:
            continue
        for asset in scope.members(zone):
            level = _level(get_purdue_level(asset))
            if level is not None and level < zone_level:
                yield asset, _('{asset} is at Purdue level {level}, below level {zone_level} of its zone {zone} (a '
                               "zone's level is its most critical one)").format(
                    asset=asset, level=get_purdue_level(asset), zone_level=zone.purdue_level, zone=zone)


@check('level-vs-zone-type', _('Asset level does not fit the zone type'), WARNING)
def level_vs_zone_type(scope):
    for zone in scope.zones:
        for asset in scope.members(zone):
            level = _level(get_purdue_level(asset))
            if level is None:
                continue
            if zone.zone_type in (ZoneTypeChoices.ENTERPRISE, ZoneTypeChoices.EXTERNAL) and level <= 2:
                yield asset, _('{asset} (level {level}) is a control asset in the {type} zone {zone}').format(
                    asset=asset, level=get_purdue_level(asset), type=zone.get_zone_type_display(), zone=zone)
            elif zone.zone_type in (ZoneTypeChoices.OT, ZoneTypeChoices.SAFETY) and level >= 4:
                yield asset, _('{asset} (level {level}) is an enterprise asset in the {type} zone {zone}').format(
                    asset=asset, level=get_purdue_level(asset), type=zone.get_zone_type_display(), zone=zone)


@check('asset-in-several-zones', _('Asset in more than one zone'), WARNING)
def asset_in_several_zones(scope):
    zones_of = defaultdict(list)
    for zone in scope.zones:
        for asset in scope.members(zone):
            zones_of[asset].append(zone)
    for asset, zones in zones_of.items():
        # A zone and its own sub-zone count once: keep the most specific zone of each chain
        specific = [z for z in zones if not any(other.pk != z.pk and z.pk in scope.ancestors(other)
                                                for other in zones)]
        if len(specific) > 1:
            yield asset, _('{asset} is in zones {zones}').format(
                asset=asset, zones=', '.join(str(z) for z in sorted(specific, key=lambda z: z.name)))


@check('asset-without-zone', _('Asset in no zone'), WARNING)
def asset_without_zone(scope):
    from dcim.models import Device
    from virtualization.models import VirtualMachine

    site_ids = {z.site_id for z in scope.zones if z.site_id}
    if not site_ids:
        return
    for model in (Device, VirtualMachine):
        qs = scope.visible(model.objects.filter(site_id__in=site_ids, ot_zones__isnull=True))
        for asset in qs.select_related('site'):
            # Only assets that take part in the network or have a Purdue level; not patch panels and PDUs
            if asset.primary_ip4_id or get_purdue_level(asset):
                yield asset, _('{asset} at {site} is in no zone').format(asset=asset, site=asset.site)


@check('capability-below-target', _('Device capability (SL-C) below the zone SL-T'), WARNING)
def capability_below_target(scope):
    for zone in scope.zones:
        if not zone.sl_target:
            continue
        for device in zone.devices.all():
            frs = sl.below(get_sl_capability(device), zone.sl_target)
            if frs:
                yield device, _('{device} SL-C {slc} is below SL-T {slt} of zone {zone} in {frs}').format(
                    device=device, slc=sl.display(get_sl_capability(device)), slt=sl.display(zone.sl_target),
                    zone=zone, frs=', '.join(frs))


def _secure_zone_devices(scope):
    """(zone, device, EndOfSupport) for devices with a lifecycle date in zones with an SL-T of 2 or more."""
    ends = scope.end_of_support()
    if not ends:
        return
    for zone in scope.zones:
        if not zone.sl_target or max(zone.sl_target) < 2:
            continue
        for device in zone.devices.all():
            if device.pk in ends:
                yield zone, device, ends[device.pk]


@check('end-of-support', _('Device past its end of support in a zone with SL-T 2 or more'), WARNING)
def end_of_support(scope):
    for zone, device, end in _secure_zone_devices(scope):
        if end.passed:
            yield device, _('{device} in zone {zone} (SL-T {slt}): {source} reached end of {kind} on {date}').format(
                device=device, zone=zone, slt=sl.display(zone.sl_target), source=end.source, kind=end.kind,
                date=end.date.isoformat())


@check('end-of-support-ahead', _('Device reaches its end of support within a year (zone SL-T 2 or more)'), INFO)
def end_of_support_ahead(scope):
    for zone, device, end in _secure_zone_devices(scope):
        if end.ahead:
            yield device, _('{device} in zone {zone} (SL-T {slt}): {source} reaches end of {kind} on {date}').format(
                device=device, zone=zone, slt=sl.display(zone.sl_target), source=end.source, kind=end.kind,
                date=end.date.isoformat())


#
# Security levels, ownership and risk
#

@check('sl-gap', _('SL-A below SL-T'), WARNING)
def sl_gap(scope):
    for obj in scope.zones + scope.conduits:
        if obj.sl_gap:
            yield obj, _('{obj}: SL-A {sla} is below SL-T {slt} in {frs}').format(
                obj=obj, sla=sl.display(obj.sl_achieved), slt=sl.display(obj.sl_target), frs=', '.join(obj.sl_gap))


@check('conduit-below-zone-sl', _('Conduit SL-T below a zone it joins'), WARNING)
def conduit_below_zone_sl(scope):
    for conduit in scope.conduits:
        for zone in conduit.zones.all():
            frs = sl.below(conduit.sl_target, zone.sl_target)
            if frs:
                yield conduit, _('{conduit} SL-T {c} is below SL-T {z} of zone {zone} in {frs}').format(
                    conduit=conduit, c=sl.display(conduit.sl_target), z=sl.display(zone.sl_target), zone=zone,
                    frs=', '.join(frs))


@check('conduit-without-enforcement', _('Conduit without an enforcing device'), WARNING)
def conduit_without_enforcement(scope):
    for conduit in scope.conduits:
        if not conduit.enforcing_devices.all() and not conduit.enforcing_virtual_machines.all():
            yield conduit, _('{conduit} names no device or VM that enforces it').format(conduit=conduit)


@check('no-sl-target', _('No SL-T'), INFO)
def no_sl_target(scope):
    for obj in scope.zones + scope.conduits:
        if not obj.sl_target:
            yield obj, _('{obj} has no security level target').format(obj=obj)


@check('no-accountable', _('No accountable person'), INFO)
def no_accountable(scope):
    for obj in scope.zones + scope.conduits:
        if not obj.accountable_id:
            yield obj, _('{obj} has no accountable person').format(obj=obj)


@check('no-risk-assessment', _('No approved risk assessment'), INFO)
def no_risk_assessment(scope):
    latest = scope.latest_assessments()
    for zone in scope.zones:
        if ('zone', zone.pk) not in latest:
            yield zone, _('{zone} has no approved risk assessment').format(zone=zone)


@check('residual-above-tolerable', _('Residual risk above tolerable'), ERROR)
def residual_above_tolerable(scope):
    for ra in scope.latest_assessments().values():
        if ra.residual_above_tolerable:
            yield ra, _('{subject}: residual risk {residual} is above the tolerable {tolerable} ({ra})').format(
                subject=ra.subject, residual=ra.get_residual_risk_display(),
                tolerable=ra.get_tolerable_risk_display(), ra=ra)


@check('risk-assessment-due', _('Risk assessment due for review'), WARNING)
def risk_assessment_due(scope):
    today = timezone.localdate()
    for ra in scope.latest_assessments().values():
        if ra.next_review and ra.next_review <= today:
            yield ra, _('{subject}: the risk assessment of {date} was due for review on {due}').format(
                subject=ra.subject, date=ra.assessed_on, due=ra.next_review)


#
# System requirements (IEC 62443-3-3)
#

@check('requirements-without-status', _('Requirements at the SL-T without a status'), WARNING)
def requirements_without_status(scope):
    requirements, statuses = scope.requirement_statuses()
    if not requirements:
        return
    for kind, objs in (('zone', scope.zones), ('conduit', scope.conduits)):
        for obj in objs:
            missing, _claimed = open_requirements(obj, requirements, statuses[(kind, obj.pk)])
            if missing:
                yield obj, _('{obj}: {n} requirements apply at SL-T {sl} without a status: {ids}').format(
                    obj=obj, n=len(missing), sl=sl.display(obj.sl_target), ids=_identifiers(missing))


@check('requirement-not-met-for-sl-a', _('SL-A claimed with a requirement not met'), ERROR)
def requirement_not_met_for_sl_a(scope):
    requirements, statuses = scope.requirement_statuses()
    if not requirements:
        return
    for kind, objs in (('zone', scope.zones), ('conduit', scope.conduits)):
        for obj in objs:
            _missing, claimed = open_requirements(obj, requirements, statuses[(kind, obj.pk)])
            for requirement in claimed:
                yield obj, _('{obj} claims SL-A {sl} in {fr} but {requirement} is not met').format(
                    obj=obj, sl=obj.sl_achieved[requirement.fr_index],
                    fr=sl.FR_SHORT[requirement.fr_index], requirement=requirement)


#
# Flows
#

@check('expired-access', _('Allowed flow has expired'), ERROR)
def expired_access(scope):
    for flow in scope.flows.filter(allowed=FlowAllowedChoices.YES, expires__lt=timezone.localdate()):
        yield flow, _('{flow} is still marked allowed but expired on {date}').format(flow=flow, date=flow.expires)


@check('remote-access-without-expiry', _('Allowed remote access without an expiry date'), WARNING)
def remote_access_without_expiry(scope):
    for flow in scope.flows.filter(allowed=FlowAllowedChoices.YES, remote_access=True, expires__isnull=True):
        yield flow, _('{flow} allows remote access with no end date').format(flow=flow)


@check('brokered-write-without-topics', _('Writes through a broker without its topics'), WARNING)
def brokered_write_without_topics(scope):
    # Whoever may publish to the right topics on the broker controls the destination; without the topics nobody can
    # check the broker's access rules against the verdict.
    for flow in scope.flows.filter(connection=ConnectionChoices.BROKERED, topics=[]):
        if any(a in AccessChoices.MODIFYING for a in flow.access):
            yield flow, _('{flow} writes or controls through a broker, but its topics are not recorded').format(
                flow=flow)


@check('flow-without-conduit', _('Flow outside any conduit'), WARNING)
def flow_without_conduit(scope):
    for flow in scope.flows.filter(conduit__isnull=True):
        yield flow, _('{flow} runs outside any documented conduit').format(flow=flow)


@check('verdict-without-decider', _('Verdict without who decided it'), INFO)
def verdict_without_decider(scope):
    for flow in scope.flows.exclude(allowed=FlowAllowedChoices.UNKNOWN).filter(decided_by__isnull=True):
        yield flow, _('{flow} is marked {verdict} without who decided it').format(
            flow=flow, verdict=flow.get_allowed_display().lower())


@check('stale-flow', _('Flow not seen recently'), INFO)
def stale_flow(scope):
    days = stale_after_days()
    for flow in scope.flows.filter(last_seen__lt=timezone.now() - datetime.timedelta(days=days)):
        yield flow, _('{flow} was last seen {date}, more than {days} days ago').format(
            flow=flow, date=flow.last_seen.date(), days=days)


def run_checks(site=None, user=None, checks=None, severities=None):
    """All findings for a site (or all sites) as Finding objects, errors first."""
    scope = Scope(site=site, user=user)
    findings = []
    for check_id, chk in CHECKS.items():
        if checks and check_id not in checks:
            continue
        if severities and chk.severity not in severities:
            continue
        for obj, message in chk.func(scope):
            findings.append(Finding(check=check_id, severity=chk.severity, obj=obj, message=str(message)))
    return sorted(findings, key=lambda f: (SEVERITIES.index(f.severity), list(CHECKS).index(f.check)))


def summary(findings):
    """{check id: (title, severity, count)} for the checks that found something, in check order."""
    counts = defaultdict(int)
    for f in findings:
        counts[f.check] += 1
    return {cid: (CHECKS[cid].title, CHECKS[cid].severity, counts[cid]) for cid in CHECKS if counts[cid]}
