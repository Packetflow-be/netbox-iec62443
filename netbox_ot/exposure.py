"""
Exposure: the flows that matter most for the safety of the controllers, as query conditions shared by the checks,
the access map (order and "needs attention") and the flow filters.

  control zone   a zone at Purdue level 0 or 1, or a safety (SIS) zone: where the controllers are
  from outside   a flow out of a DMZ, enterprise or external zone, or out of a zone at level 3.5 or higher: from
                 the business network, a supplier or the internet, past the site's operations level
  changes        a flow whose requests write, control or program its destination

  undecided-into-control  nobody decided yet whether a flow into a control zone may exist, and it changes the
                          controllers, is remote access, or comes from outside
  outside-into-control    a flow that is allowed straight from outside into a control zone, without passing a
                          supervisory zone
"""
from django.db.models import Case, IntegerField, Q, Value, When
from django.utils.translation import gettext as _

from .choices import AccessChoices, FlowAllowedChoices, PurdueLevelChoices, ZoneTypeChoices

CONTROL_LEVELS = PurdueLevelChoices.at_or_below(PurdueLevelChoices.LEVEL_1)
OUTSIDE_LEVELS = [value for value, _label in PurdueLevelChoices.CHOICES if float(value) >= 3.5]
OUTSIDE_TYPES = (ZoneTypeChoices.DMZ, ZoneTypeChoices.ENTERPRISE, ZoneTypeChoices.EXTERNAL)


def into_control():
    return Q(destination_zone__purdue_level__in=CONTROL_LEVELS) | Q(destination_zone__zone_type=ZoneTypeChoices.SAFETY)


def from_outside():
    return Q(source_zone__zone_type__in=OUTSIDE_TYPES) | Q(source_zone__purdue_level__in=OUTSIDE_LEVELS)


def changes():
    return Q(access__overlap=list(AccessChoices.MODIFYING))


def undecided_into_control():
    return Q(allowed=FlowAllowedChoices.UNKNOWN) & into_control() & (changes() | Q(remote_access=True) | from_outside())


def outside_into_control():
    return Q(allowed=FlowAllowedChoices.YES) & into_control() & from_outside()


def exposure_order():
    """Within one verdict: 0 changes and comes from outside or remotely, 1 changes, 2 outside or remote, 3 the rest."""
    outside = from_outside() | Q(remote_access=True)
    return Case(
        When(changes() & outside, then=Value(0)),
        When(changes(), then=Value(1)),
        When(outside, then=Value(2)),
        default=Value(3),
        output_field=IntegerField(),
    )


def is_control_zone(zone):
    return zone.zone_type == ZoneTypeChoices.SAFETY or zone.purdue_level in CONTROL_LEVELS


def is_outside_zone(zone):
    return zone.zone_type in OUTSIDE_TYPES or zone.purdue_level in OUTSIDE_LEVELS


def changes_flow(flow):
    return any(a in AccessChoices.MODIFYING for a in flow.access or ())


def reasons(flow):
    """Why an undecided flow into a control zone needs a decision first, as short phrases."""
    labels = dict(AccessChoices.CHOICES)
    found = []
    if changes_flow(flow):
        found.append(', '.join(str(labels[a]).lower() for a in flow.access if a in AccessChoices.MODIFYING))
    if flow.remote_access:
        found.append(str(_('remote access')))
    if is_outside_zone(flow.source_zone):
        found.append(str(_('from the {type} zone {zone}').format(
            type=flow.source_zone.get_zone_type_display(), zone=flow.source_zone)))
    return found
