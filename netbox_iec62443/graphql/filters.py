from typing import Annotated

import strawberry
import strawberry_django
from strawberry.scalars import ID
from strawberry_django import FilterLookup, StrFilterLookup

from netbox.graphql.filters import PrimaryModelFilter, register_filter
from tenancy.graphql.filter_mixins import TenancyFilterMixin

from .. import models

__all__ = (
    'ConduitFilter', 'FieldbusFilter', 'FlowFilter', 'FlowHopFilter', 'IndustrialServiceFilter',
    'RequirementStatusFilter', 'RiskAssessmentFilter', 'SystemRequirementFilter', 'ZoneFilter',
)


@register_filter(models.Zone, lookups=True)
class ZoneFilter(TenancyFilterMixin, PrimaryModelFilter):
    name: StrFilterLookup[str] | None = strawberry_django.filter_field()
    slug: StrFilterLookup[str] | None = strawberry_django.filter_field()
    site_id: ID | None = strawberry_django.filter_field()
    zone_type: StrFilterLookup[str] | None = strawberry_django.filter_field()
    purdue_level: StrFilterLookup[str] | None = strawberry_django.filter_field()
    parent_id: ID | None = strawberry_django.filter_field()
    accountable_id: ID | None = strawberry_django.filter_field()
    wireless: FilterLookup[bool] | None = strawberry_django.filter_field()
    temporary_devices: FilterLookup[bool] | None = strawberry_django.filter_field()


@register_filter(models.Conduit, lookups=True)
class ConduitFilter(PrimaryModelFilter):
    name: StrFilterLookup[str] | None = strawberry_django.filter_field()
    site_id: ID | None = strawberry_django.filter_field()
    accountable_id: ID | None = strawberry_django.filter_field()
    zones: Annotated['ZoneFilter', strawberry.lazy('netbox_iec62443.graphql.filters')] | None = (
        strawberry_django.filter_field()
    )


@register_filter(models.Flow, lookups=True)
class FlowFilter(PrimaryModelFilter):
    name: StrFilterLookup[str] | None = strawberry_django.filter_field()
    conduit_id: ID | None = strawberry_django.filter_field()
    source_zone: Annotated['ZoneFilter', strawberry.lazy('netbox_iec62443.graphql.filters')] | None = (
        strawberry_django.filter_field()
    )
    source_zone_id: ID | None = strawberry_django.filter_field()
    destination_zone: Annotated['ZoneFilter', strawberry.lazy('netbox_iec62443.graphql.filters')] | None = (
        strawberry_django.filter_field()
    )
    destination_zone_id: ID | None = strawberry_django.filter_field()
    protocol: StrFilterLookup[str] | None = strawberry_django.filter_field()
    connection: StrFilterLookup[str] | None = strawberry_django.filter_field()
    broker_zone_id: ID | None = strawberry_django.filter_field()
    allowed: StrFilterLookup[str] | None = strawberry_django.filter_field()
    remote_access: FilterLookup[bool] | None = strawberry_django.filter_field()
    decided_by_id: ID | None = strawberry_django.filter_field()


@register_filter(models.FlowHop, lookups=True)
class FlowHopFilter(PrimaryModelFilter):
    flow_id: ID | None = strawberry_django.filter_field()
    position: FilterLookup[int] | None = strawberry_django.filter_field()
    device_id: ID | None = strawberry_django.filter_field()
    virtual_machine_id: ID | None = strawberry_django.filter_field()
    tunnel_id: ID | None = strawberry_django.filter_field()


@register_filter(models.Fieldbus, lookups=True)
class FieldbusFilter(PrimaryModelFilter):
    name: StrFilterLookup[str] | None = strawberry_django.filter_field()
    site_id: ID | None = strawberry_django.filter_field()
    zone_id: ID | None = strawberry_django.filter_field()
    medium: StrFilterLookup[str] | None = strawberry_django.filter_field()
    protocol: StrFilterLookup[str] | None = strawberry_django.filter_field()
    gateway_id: ID | None = strawberry_django.filter_field()


@register_filter(models.IndustrialService, lookups=True)
class IndustrialServiceFilter(PrimaryModelFilter):
    device_id: ID | None = strawberry_django.filter_field()
    virtual_machine_id: ID | None = strawberry_django.filter_field()
    protocol: StrFilterLookup[str] | None = strawberry_django.filter_field()
    role: StrFilterLookup[str] | None = strawberry_django.filter_field()
    service_id: ID | None = strawberry_django.filter_field()
    fieldbus_id: ID | None = strawberry_django.filter_field()
    address: StrFilterLookup[str] | None = strawberry_django.filter_field()


@register_filter(models.RiskAssessment, lookups=True)
class RiskAssessmentFilter(PrimaryModelFilter):
    zone_id: ID | None = strawberry_django.filter_field()
    conduit_id: ID | None = strawberry_django.filter_field()
    kind: StrFilterLookup[str] | None = strawberry_django.filter_field()
    status: StrFilterLookup[str] | None = strawberry_django.filter_field()
    residual_risk: StrFilterLookup[str] | None = strawberry_django.filter_field()
    tolerable_risk: StrFilterLookup[str] | None = strawberry_django.filter_field()


@register_filter(models.SystemRequirement, lookups=True)
class SystemRequirementFilter(PrimaryModelFilter):
    edition: StrFilterLookup[str] | None = strawberry_django.filter_field()
    identifier: StrFilterLookup[str] | None = strawberry_django.filter_field()
    foundational_requirement: StrFilterLookup[str] | None = strawberry_django.filter_field()
    parent_id: ID | None = strawberry_django.filter_field()
    security_level: FilterLookup[int] | None = strawberry_django.filter_field()


@register_filter(models.RequirementStatus, lookups=True)
class RequirementStatusFilter(PrimaryModelFilter):
    zone_id: ID | None = strawberry_django.filter_field()
    conduit_id: ID | None = strawberry_django.filter_field()
    requirement_id: ID | None = strawberry_django.filter_field()
    status: StrFilterLookup[str] | None = strawberry_django.filter_field()
    risk_assessment_id: ID | None = strawberry_django.filter_field()
    assessed_by_id: ID | None = strawberry_django.filter_field()
