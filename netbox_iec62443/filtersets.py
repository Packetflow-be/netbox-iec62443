import django_filters
from django.db.models import Q
from django.utils.translation import gettext as _

from dcim.models import Device, Interface, Site
from ipam.models import Prefix
from netbox.filtersets import PrimaryModelFilterSet
from tenancy.filtersets import TenancyFilterSet
from utilities.filtersets import register_filterset
from virtualization.models import VirtualMachine

from .choices import (
    ConduitAllowedChoices,
    ConduitDirectionChoices,
    FieldbusMediumChoices,
    IndustrialProtocolChoices,
    PurdueLevelChoices,
    SecurityLevelChoices,
    ServiceRoleChoices,
)
from .models import Conduit, Fieldbus, IndustrialService, Zone

__all__ = ('ConduitFilterSet', 'FieldbusFilterSet', 'IndustrialServiceFilterSet', 'ZoneFilterSet')


@register_filterset
class ZoneFilterSet(PrimaryModelFilterSet, TenancyFilterSet):
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
    purdue_level = django_filters.MultipleChoiceFilter(choices=PurdueLevelChoices, distinct=False)
    security_level_target = django_filters.MultipleChoiceFilter(choices=SecurityLevelChoices, distinct=False)
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

    class Meta:
        model = Zone
        fields = ('id', 'name', 'slug', 'description')

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
class ConduitFilterSet(PrimaryModelFilterSet):
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
    direction = django_filters.MultipleChoiceFilter(choices=ConduitDirectionChoices, distinct=False)
    allowed = django_filters.MultipleChoiceFilter(choices=ConduitAllowedChoices, distinct=False)
    remote_access = django_filters.BooleanFilter()

    class Meta:
        model = Conduit
        fields = ('id', 'name', 'protocols', 'via', 'description')

    def search(self, queryset, name, value):
        if not value.strip():
            return queryset
        return queryset.filter(
            Q(name__icontains=value) |
            Q(protocols__icontains=value) |
            Q(via__icontains=value) |
            Q(evidence__icontains=value) |
            Q(description__icontains=value) |
            Q(comments__icontains=value)
        )

    def filter_zone(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(Q(source_zone__in=value) | Q(destination_zone__in=value))

    def filter_site(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(Q(source_zone__site__in=value) | Q(destination_zone__site__in=value))


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
    interface_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Interface.objects.all(),
        distinct=False,
        label=_('Interface (ID)'),
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
    port = django_filters.NumberFilter(field_name='ports', lookup_expr='contains', method='filter_port',
                                       label=_('Port'))

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
        return queryset.filter(ports__contains=[int(value)])

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
