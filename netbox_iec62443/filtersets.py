import datetime

import django_filters
from django.db.models import Func, Q, TextField, Value
from django.utils import timezone
from django.utils.translation import gettext as _

from dcim.models import Device, Site
from ipam.models import Prefix, Service
from netbox.filtersets import PrimaryModelFilterSet
from tenancy.filtersets import TenancyFilterSet
from tenancy.models import Contact
from utilities.filtersets import register_filterset
from virtualization.models import VirtualMachine
from vpn.models import Tunnel

from . import sl
from .choices import (
    AccessChoices,
    ConnectionChoices,
    FieldbusMediumChoices,
    FlowAllowedChoices,
    FlowProtocolChoices,
    IndustrialProtocolChoices,
    PurdueLevelChoices,
    RiskAssessmentKindChoices,
    RiskAssessmentStatusChoices,
    RiskLevelChoices,
    ServiceRoleChoices,
    ZoneTypeChoices,
)
from .models import Conduit, Fieldbus, Flow, FlowHop, IndustrialService, RiskAssessment, Zone, stale_after_days

__all__ = (
    'ConduitFilterSet', 'FieldbusFilterSet', 'FlowFilterSet', 'FlowHopFilterSet', 'IndustrialServiceFilterSet',
    'RiskAssessmentFilterSet', 'ZoneFilterSet',
)


class SecurityLevelFilterMixin(django_filters.FilterSet):
    """Filters shared by zones and conduits: SL-T set, SL-A below SL-T, accountable person."""
    has_sl_target = django_filters.BooleanFilter(
        field_name='sl_target', lookup_expr='isnull', exclude=True, label=_('Has an SL-T'),
    )
    sl_gap = django_filters.BooleanFilter(method='filter_sl_gap', label=_('SL-A below SL-T'))
    accountable_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Contact.objects.all(),
        distinct=False,
        label=_('Accountable (ID)'),
    )

    def filter_sl_gap(self, queryset, name, value):
        if value is None:
            return queryset
        q = sl.gap_q('sl_achieved', 'sl_target')
        return queryset.filter(q) if value else queryset.exclude(q)


def port_mappings_q(field, port):
    """Q matching a port number (any transport) in a port_mappings array at `field`."""
    from ipam.choices import ServiceProtocolChoices
    return Q(**{f'{field}__overlap': [f'{proto}/{int(port)}' for proto in ServiceProtocolChoices.values()]})


@register_filterset
class ZoneFilterSet(SecurityLevelFilterMixin, PrimaryModelFilterSet, TenancyFilterSet):
    site_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Site.objects.all(),
        distinct=False,
        label=_('Site (ID)'),
    )
    site = django_filters.ModelMultipleChoiceFilter(
        field_name='site__slug',
        queryset=Site.objects.all(),
        distinct=False,
        to_field_name='slug',
        label=_('Site (slug)'),
    )
    zone_type = django_filters.MultipleChoiceFilter(choices=ZoneTypeChoices, distinct=False)
    purdue_level = django_filters.MultipleChoiceFilter(choices=PurdueLevelChoices, distinct=False)
    parent_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Zone.objects.all(),
        distinct=False,
        label=_('Parent zone (ID)'),
    )
    device_id = django_filters.ModelMultipleChoiceFilter(
        field_name='devices',
        queryset=Device.objects.all(),
        label=_('Device (ID)'),
    )
    virtual_machine_id = django_filters.ModelMultipleChoiceFilter(
        field_name='virtual_machines',
        queryset=VirtualMachine.objects.all(),
        label=_('Virtual machine (ID)'),
    )
    prefix_id = django_filters.ModelMultipleChoiceFilter(
        field_name='prefixes',
        queryset=Prefix.objects.all(),
        label=_('Prefix (ID)'),
    )
    conduit_id = django_filters.ModelMultipleChoiceFilter(
        field_name='conduits',
        queryset=Conduit.objects.all(),
        label=_('Conduit (ID)'),
    )

    class Meta:
        model = Zone
        fields = ('id', 'name', 'slug', 'wireless', 'temporary_devices', 'description')

    def search(self, queryset, name, value):
        if not value.strip():
            return queryset
        return queryset.filter(
            Q(name__icontains=value) |
            Q(slug__icontains=value) |
            Q(description__icontains=value) |
            Q(comments__icontains=value)
        )


@register_filterset
class ConduitFilterSet(SecurityLevelFilterMixin, PrimaryModelFilterSet):
    site_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Site.objects.all(),
        distinct=False,
        label=_('Site (ID)'),
    )
    site = django_filters.ModelMultipleChoiceFilter(
        field_name='site__slug',
        queryset=Site.objects.all(),
        distinct=False,
        to_field_name='slug',
        label=_('Site (slug)'),
    )
    zone_id = django_filters.ModelMultipleChoiceFilter(
        field_name='zones',
        queryset=Zone.objects.all(),
        label=_('Zone (ID)'),
    )
    enforcing_device_id = django_filters.ModelMultipleChoiceFilter(
        field_name='enforcing_devices',
        queryset=Device.objects.all(),
        label=_('Enforcing device (ID)'),
    )
    enforcing_virtual_machine_id = django_filters.ModelMultipleChoiceFilter(
        field_name='enforcing_virtual_machines',
        queryset=VirtualMachine.objects.all(),
        label=_('Enforcing virtual machine (ID)'),
    )

    class Meta:
        model = Conduit
        fields = ('id', 'name', 'description')

    def search(self, queryset, name, value):
        if not value.strip():
            return queryset
        return queryset.filter(
            Q(name__icontains=value) |
            Q(description__icontains=value) |
            Q(comments__icontains=value)
        )


@register_filterset
def _topics_text():
    """A flow's topics as one text, so "a topic contains X" stays a plain filter in one query."""
    return Func('topics', Value('\n'), function='array_to_string', output_field=TextField())


class FlowFilterSet(PrimaryModelFilterSet):
    conduit_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Conduit.objects.all(),
        distinct=False,
        label=_('Conduit (ID)'),
    )
    has_conduit = django_filters.BooleanFilter(
        field_name='conduit', lookup_expr='isnull', exclude=True, label=_('Has a conduit'),
    )
    source_zone_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Zone.objects.all(),
        distinct=False,
        label=_('Source zone (ID)'),
    )
    destination_zone_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Zone.objects.all(),
        distinct=False,
        label=_('Destination zone (ID)'),
    )
    zone_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Zone.objects.all(),
        method='filter_zone',
        label=_('Zone (ID), either end'),
    )
    site_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Site.objects.all(),
        method='filter_site',
        label=_('Site (ID) of either zone'),
    )
    protocol = django_filters.MultipleChoiceFilter(choices=FlowProtocolChoices, distinct=False)
    port = django_filters.NumberFilter(method='filter_port', label=_('Port'))
    access = django_filters.MultipleChoiceFilter(
        choices=AccessChoices, method='filter_access', label=_('Access (any of)'),
    )
    modifying = django_filters.BooleanFilter(method='filter_modifying', label=_('Writes, controls or programs'))
    connection = django_filters.MultipleChoiceFilter(choices=ConnectionChoices, distinct=False)
    broker_zone_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Zone.objects.all(),
        distinct=False,
        label=_('Broker zone (ID)'),
    )
    outbound_only = django_filters.BooleanFilter(
        method='filter_outbound_only', label=_('No inbound connection into the destination zone'),
    )
    topic = django_filters.CharFilter(method='filter_topic', label=_('Topic (contains)'))
    allowed = django_filters.MultipleChoiceFilter(choices=FlowAllowedChoices, distinct=False)
    remote_access = django_filters.BooleanFilter()
    decided_by_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Contact.objects.all(),
        distinct=False,
        label=_('Decided by (ID)'),
    )
    expired = django_filters.BooleanFilter(method='filter_expired', label=_('Allowed, but expired'))
    review_due = django_filters.BooleanFilter(method='filter_review_due', label=_('Review due'))
    stale = django_filters.BooleanFilter(method='filter_stale', label=_('Not seen recently'))
    hop_device_id = django_filters.ModelMultipleChoiceFilter(
        field_name='hops__device',
        queryset=Device.objects.all(),
        label=_('Runs through device (ID)'),
    )
    hop_virtual_machine_id = django_filters.ModelMultipleChoiceFilter(
        field_name='hops__virtual_machine',
        queryset=VirtualMachine.objects.all(),
        label=_('Runs through virtual machine (ID)'),
    )
    hop_tunnel_id = django_filters.ModelMultipleChoiceFilter(
        field_name='hops__tunnel',
        queryset=Tunnel.objects.all(),
        label=_('Runs through tunnel (ID)'),
    )

    class Meta:
        model = Flow
        fields = ('id', 'name', 'decided_on', 'review_by', 'expires', 'first_seen', 'last_seen', 'description')

    def search(self, queryset, name, value):
        if not value.strip():
            return queryset
        return queryset.annotate(_topics=_topics_text()).filter(
            Q(name__icontains=value) |
            Q(evidence__icontains=value) |
            Q(description__icontains=value) |
            Q(comments__icontains=value) |
            Q(_topics__icontains=value)
        )

    def filter_zone(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(Q(source_zone__in=value) | Q(destination_zone__in=value) | Q(broker_zone__in=value))

    def filter_site(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(Q(source_zone__site__in=value) | Q(destination_zone__site__in=value))

    def filter_outbound_only(self, queryset, name, value):
        if value is None:
            return queryset
        q = Q(connection__in=ConnectionChoices.OUTBOUND_ONLY)
        return queryset.filter(q) if value else queryset.exclude(q)

    def filter_topic(self, queryset, name, value):
        value = value.strip()
        if not value:
            return queryset
        return queryset.annotate(_topics=_topics_text()).filter(_topics__icontains=value)

    def filter_port(self, queryset, name, value):
        if value is None:
            return queryset
        return queryset.filter(port_mappings_q('port_mappings', value))

    def filter_access(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(access__overlap=list(value))

    def filter_modifying(self, queryset, name, value):
        if value is None:
            return queryset
        q = Q(access__overlap=list(AccessChoices.MODIFYING))
        return queryset.filter(q) if value else queryset.exclude(q)

    def filter_expired(self, queryset, name, value):
        if value is None:
            return queryset
        q = Q(allowed=FlowAllowedChoices.YES, expires__lt=timezone.localdate())
        return queryset.filter(q) if value else queryset.exclude(q)

    def filter_review_due(self, queryset, name, value):
        if value is None:
            return queryset
        q = Q(review_by__lte=timezone.localdate())
        return queryset.filter(q) if value else queryset.exclude(q)

    def filter_stale(self, queryset, name, value):
        if value is None:
            return queryset
        q = Q(last_seen__lt=timezone.now() - datetime.timedelta(days=stale_after_days()))
        return queryset.filter(q) if value else queryset.exclude(q)


@register_filterset
class FlowHopFilterSet(PrimaryModelFilterSet):
    flow_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Flow.objects.all(),
        distinct=False,
        label=_('Flow (ID)'),
    )
    device_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Device.objects.all(),
        distinct=False,
        label=_('Device (ID)'),
    )
    virtual_machine_id = django_filters.ModelMultipleChoiceFilter(
        queryset=VirtualMachine.objects.all(),
        distinct=False,
        label=_('Virtual machine (ID)'),
    )
    tunnel_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Tunnel.objects.all(),
        distinct=False,
        label=_('Tunnel (ID)'),
    )

    class Meta:
        model = FlowHop
        fields = ('id', 'position', 'description')

    def search(self, queryset, name, value):
        if not value.strip():
            return queryset
        return queryset.filter(
            Q(flow__name__icontains=value) |
            Q(device__name__icontains=value) |
            Q(virtual_machine__name__icontains=value) |
            Q(tunnel__name__icontains=value) |
            Q(description__icontains=value)
        )


@register_filterset
class RiskAssessmentFilterSet(PrimaryModelFilterSet):
    zone_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Zone.objects.all(),
        distinct=False,
        label=_('Zone (ID)'),
    )
    conduit_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Conduit.objects.all(),
        distinct=False,
        label=_('Conduit (ID)'),
    )
    site_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Site.objects.all(),
        method='filter_site',
        label=_('Site (ID) of the zone or conduit'),
    )
    kind = django_filters.MultipleChoiceFilter(choices=RiskAssessmentKindChoices, distinct=False)
    status = django_filters.MultipleChoiceFilter(choices=RiskAssessmentStatusChoices, distinct=False)
    unmitigated_risk = django_filters.MultipleChoiceFilter(choices=RiskLevelChoices, distinct=False)
    residual_risk = django_filters.MultipleChoiceFilter(choices=RiskLevelChoices, distinct=False)
    tolerable_risk = django_filters.MultipleChoiceFilter(choices=RiskLevelChoices, distinct=False)
    residual_above_tolerable = django_filters.BooleanFilter(
        method='filter_residual_above_tolerable', label=_('Residual risk above tolerable'),
    )
    review_due = django_filters.BooleanFilter(method='filter_review_due', label=_('Review due'))
    assessed_by_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Contact.objects.all(),
        distinct=False,
        label=_('Assessed by (ID)'),
    )
    approved_by_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Contact.objects.all(),
        distinct=False,
        label=_('Approved by (ID)'),
    )

    class Meta:
        model = RiskAssessment
        fields = ('id', 'assessed_on', 'approved_on', 'next_review', 'method', 'description')

    def search(self, queryset, name, value):
        if not value.strip():
            return queryset
        return queryset.filter(
            Q(zone__name__icontains=value) |
            Q(conduit__name__icontains=value) |
            Q(method__icontains=value) |
            Q(threats__icontains=value) |
            Q(vulnerabilities__icontains=value) |
            Q(consequences__icontains=value) |
            Q(countermeasures__icontains=value) |
            Q(description__icontains=value)
        )

    def filter_site(self, queryset, name, value):
        if not value:
            return queryset
        q = Q(zone__site__in=value) | Q(conduit__site__in=value) | Q(conduit__zones__site__in=value)
        return queryset.filter(q).distinct()

    def filter_residual_above_tolerable(self, queryset, name, value):
        if value is None:
            return queryset
        levels = RiskLevelChoices.values()
        q = Q()
        for i, tolerable in enumerate(levels):
            q |= Q(tolerable_risk=tolerable, residual_risk__in=levels[i + 1:])
        return queryset.filter(q) if value else queryset.exclude(q)

    def filter_review_due(self, queryset, name, value):
        if value is None:
            return queryset
        q = Q(next_review__lte=timezone.localdate())
        return queryset.filter(q) if value else queryset.exclude(q)


@register_filterset
class FieldbusFilterSet(PrimaryModelFilterSet):
    site_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Site.objects.all(),
        distinct=False,
        label=_('Site (ID)'),
    )
    zone_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Zone.objects.all(),
        distinct=False,
        label=_('Zone (ID)'),
    )
    gateway_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Device.objects.all(),
        distinct=False,
        label=_('Gateway (ID)'),
    )
    medium = django_filters.MultipleChoiceFilter(choices=FieldbusMediumChoices, distinct=False)
    protocol = django_filters.MultipleChoiceFilter(choices=IndustrialProtocolChoices, distinct=False)

    class Meta:
        model = Fieldbus
        fields = ('id', 'name', 'description')

    def search(self, queryset, name, value):
        if not value.strip():
            return queryset
        return queryset.filter(
            Q(name__icontains=value) |
            Q(description__icontains=value) |
            Q(comments__icontains=value)
        )


@register_filterset
class IndustrialServiceFilterSet(PrimaryModelFilterSet):
    device_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Device.objects.all(),
        distinct=False,
        label=_('Device (ID)'),
    )
    device = django_filters.ModelMultipleChoiceFilter(
        field_name='device__name',
        queryset=Device.objects.all(),
        distinct=False,
        to_field_name='name',
        label=_('Device (name)'),
    )
    virtual_machine_id = django_filters.ModelMultipleChoiceFilter(
        queryset=VirtualMachine.objects.all(),
        distinct=False,
        label=_('Virtual machine (ID)'),
    )
    service_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Service.objects.all(),
        distinct=False,
        label=_('Application service (ID)'),
    )
    fieldbus_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Fieldbus.objects.all(),
        distinct=False,
        label=_('Fieldbus (ID)'),
    )
    site_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Site.objects.all(),
        method='filter_site',
        label=_('Site (ID) of the device or VM'),
    )
    zone_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Zone.objects.all(),
        method='filter_zone',
        label=_('Zone (ID) of the device or VM'),
    )
    protocol = django_filters.MultipleChoiceFilter(choices=IndustrialProtocolChoices, distinct=False)
    role = django_filters.MultipleChoiceFilter(choices=ServiceRoleChoices, distinct=False)
    port = django_filters.NumberFilter(method='filter_port', label=_('Port'))

    class Meta:
        model = IndustrialService
        fields = ('id', 'address', 'description')

    def search(self, queryset, name, value):
        if not value.strip():
            return queryset
        return queryset.filter(
            Q(device__name__icontains=value) |
            Q(virtual_machine__name__icontains=value) |
            Q(address__icontains=value) |
            Q(description__icontains=value) |
            Q(evidence__icontains=value)
        )

    def filter_port(self, queryset, name, value):
        if value is None:
            return queryset
        return queryset.filter(port_mappings_q('service__port_mappings', value))

    def filter_site(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(Q(device__site__in=value) | Q(virtual_machine__site__in=value))

    def filter_zone(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(device__iec62443_zones__in=value) | Q(virtual_machine__iec62443_zones__in=value)
        ).distinct()
