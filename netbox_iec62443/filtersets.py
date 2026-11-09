import django_filters
from django.db.models import Q
from django.utils.translation import gettext as _

from dcim.models import Device, Site
from ipam.models import Prefix
from netbox.filtersets import PrimaryModelFilterSet
from tenancy.filtersets import TenancyFilterSet
from utilities.filtersets import register_filterset
from virtualization.models import VirtualMachine

from .choices import ConduitAllowedChoices, ConduitDirectionChoices, PurdueLevelChoices, SecurityLevelChoices
from .models import Conduit, Zone

__all__ = ('ConduitFilterSet', 'ZoneFilterSet')


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
