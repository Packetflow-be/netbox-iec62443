"""
The access map: every flow into a zone at Purdue level <= N (default 2), i.e. every path to the controllers, with
its "allowed?" verdict. Not allowed first, then allowed-but-expired, unknown, and allowed. The diagram that goes
with it is in accessdiagram.py.
"""
import datetime

from django.db.models import Case, IntegerField, Q, Value, When
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .accessdiagram import access_map_diagram, access_map_svg  # noqa: F401 (imported from here)
from .choices import ConnectionChoices, FlowAllowedChoices, PurdueLevelChoices
from .models import Flow, Zone, stale_after_days

# The four verdicts of the access map, worst first; the position is the value of `verdict_order`
VERDICTS = ('no', 'expired', 'unknown', 'yes')
VERDICT_CHOICES = (
    ('no', _('Not allowed')),
    ('expired', _('Allowed, expired')),
    ('unknown', _('Unknown')),
    ('yes', _('Allowed')),
)


def verdict_order():
    """0 not allowed, 1 allowed but expired, 2 unknown, 3 allowed."""
    return Case(
        When(allowed=FlowAllowedChoices.NO, then=Value(0)),
        When(allowed=FlowAllowedChoices.YES, expires__lt=timezone.localdate(), then=Value(1)),
        When(allowed=FlowAllowedChoices.UNKNOWN, then=Value(2)),
        default=Value(3),
        output_field=IntegerField(),
    )


def access_map_flows(queryset=None, site=None, max_level=PurdueLevelChoices.LEVEL_2, verdict=(), protocol=(),
                     connection=(), zones=(), remote_access=None):
    """
    Flows into zones at Purdue level <= max_level, from any zone of the site or into one. The other arguments
    narrow it down: verdicts (VERDICTS), protocols, connection models, zones (flows from, into or brokered in
    one of them) and remote access only (True) or without (False).
    """
    levels = PurdueLevelChoices.at_or_below(max_level)
    qs = (queryset if queryset is not None else Flow.objects.all()).select_related(
        'source_zone__site', 'destination_zone__site', 'broker_zone', 'conduit',
    ).prefetch_related('hops__device', 'hops__virtual_machine', 'hops__tunnel')
    if site is not None:
        qs = qs.filter(Q(source_zone__site=site) | Q(destination_zone__site=site))
    qs = qs.filter(destination_zone__purdue_level__in=levels)
    if protocol:
        qs = qs.filter(protocol__in=protocol)
    if connection:
        qs = qs.filter(connection__in=connection)
    if zones:
        qs = qs.filter(Q(source_zone__in=zones) | Q(destination_zone__in=zones) | Q(broker_zone__in=zones))
    if remote_access is not None:
        qs = qs.filter(remote_access=remote_access)
    qs = qs.annotate(verdict_order=verdict_order())
    if verdict:
        qs = qs.filter(verdict_order__in=[VERDICTS.index(v) for v in verdict if v in VERDICTS])
    return qs.order_by('verdict_order', 'destination_zone__purdue_level', 'destination_zone__name', 'name')


def attention(queryset):
    """
    Counts of flows that need a person: allowed but expired, review due, not seen for a while, no conduit; and the
    flows that reach their destination over a connection opened from its own side (reverse connect, a broker),
    which a firewall rule on inbound traffic into that zone does not stop.
    """
    today = timezone.localdate()
    stale_before = timezone.now() - datetime.timedelta(days=stale_after_days())
    return {
        'expired': queryset.filter(allowed=FlowAllowedChoices.YES, expires__lt=today).count(),
        'review_due': queryset.filter(review_by__lte=today).count(),
        'stale': queryset.filter(last_seen__lt=stale_before).count(),
        'no_conduit': queryset.filter(conduit__isnull=True).count(),
        'outbound_only': queryset.filter(connection__in=ConnectionChoices.OUTBOUND_ONLY).count(),
        'stale_after_days': stale_after_days(),
    }




def site_zones(site):
    return Zone.objects.filter(site=site) if site is not None else Zone.objects.none()


def accessmap_labels():
    """The texts the diagram's script shows in its detail panel."""
    return {
        'verdicts': {value: str(label) for value, label in VERDICT_CHOICES},
        'from': str(_('From zone')),
        'to': str(_('To zone')),
        'flow': str(_('Flow')),
        'protocol': str(_('Protocol / ports')),
        'verdict': str(_('Allowed')),
        'remote': str(_('remote access')),
        'open': str(_('Open the zone')),
        'focus': str(_('Only this zone and its neighbours')),
        'flows': str(_('flows')),
        'inside': str(_('Between the zones inside')),
        'subzones': str(_('Sub-zones')),
        'close': str(_('Close')),
        'none': str(_('No flows on the map for this zone.')),
    }
