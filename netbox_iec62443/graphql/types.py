from typing import TYPE_CHECKING, Annotated

import strawberry

from netbox.graphql.types import PrimaryObjectType, register_type

from .. import models
from .filters import (
    ConduitFilter,
    FieldbusFilter,
    FlowFilter,
    FlowHopFilter,
    IndustrialServiceFilter,
    RequirementStatusFilter,
    RiskAssessmentFilter,
    SystemRequirementFilter,
    ZoneFilter,
)

if TYPE_CHECKING:
    from dcim.graphql.types import DeviceType, SiteType
    from ipam.graphql.types import PrefixType, ServiceType
    from tenancy.graphql.types import ContactType, TenantType
    from virtualization.graphql.types import VirtualMachineType
    from vpn.graphql.types import TunnelType

__all__ = (
    'ConduitType', 'FieldbusType', 'FlowHopType', 'FlowType', 'IndustrialServiceType', 'RequirementStatusType',
    'RiskAssessmentType', 'SystemRequirementType', 'ZoneType',
)


@register_type(models.Zone, fields='__all__', filters=ZoneFilter, pagination=True)
class ZoneType(PrimaryObjectType):
    site: Annotated['SiteType', strawberry.lazy('dcim.graphql.types')] | None
    tenant: Annotated['TenantType', strawberry.lazy('tenancy.graphql.types')] | None
    parent: Annotated['ZoneType', strawberry.lazy('netbox_iec62443.graphql.types')] | None
    subzones: list[Annotated['ZoneType', strawberry.lazy('netbox_iec62443.graphql.types')]]
    accountable: Annotated['ContactType', strawberry.lazy('tenancy.graphql.types')] | None
    sl_target: list[int] | None
    sl_achieved: list[int] | None
    risk_assessments: list[Annotated['RiskAssessmentType', strawberry.lazy('netbox_iec62443.graphql.types')]]
    requirement_statuses: list[
        Annotated['RequirementStatusType', strawberry.lazy('netbox_iec62443.graphql.types')]
    ]
    devices: list[Annotated['DeviceType', strawberry.lazy('dcim.graphql.types')]]
    virtual_machines: list[Annotated['VirtualMachineType', strawberry.lazy('virtualization.graphql.types')]]
    prefixes: list[Annotated['PrefixType', strawberry.lazy('ipam.graphql.types')]]
    conduits: list[Annotated['ConduitType', strawberry.lazy('netbox_iec62443.graphql.types')]]
    flows_out: list[Annotated['FlowType', strawberry.lazy('netbox_iec62443.graphql.types')]]
    flows_in: list[Annotated['FlowType', strawberry.lazy('netbox_iec62443.graphql.types')]]


@register_type(models.Conduit, fields='__all__', filters=ConduitFilter, pagination=True)
class ConduitType(PrimaryObjectType):
    site: Annotated['SiteType', strawberry.lazy('dcim.graphql.types')] | None
    zones: list[Annotated['ZoneType', strawberry.lazy('netbox_iec62443.graphql.types')]]
    accountable: Annotated['ContactType', strawberry.lazy('tenancy.graphql.types')] | None
    sl_target: list[int] | None
    sl_achieved: list[int] | None
    risk_assessments: list[Annotated['RiskAssessmentType', strawberry.lazy('netbox_iec62443.graphql.types')]]
    requirement_statuses: list[
        Annotated['RequirementStatusType', strawberry.lazy('netbox_iec62443.graphql.types')]
    ]
    enforcing_devices: list[Annotated['DeviceType', strawberry.lazy('dcim.graphql.types')]]
    enforcing_virtual_machines: list[
        Annotated['VirtualMachineType', strawberry.lazy('virtualization.graphql.types')]
    ]
    flows: list[Annotated['FlowType', strawberry.lazy('netbox_iec62443.graphql.types')]]


@register_type(models.Flow, fields='__all__', filters=FlowFilter, pagination=True)
class FlowType(PrimaryObjectType):
    conduit: Annotated['ConduitType', strawberry.lazy('netbox_iec62443.graphql.types')] | None
    source_zone: Annotated['ZoneType', strawberry.lazy('netbox_iec62443.graphql.types')]
    destination_zone: Annotated['ZoneType', strawberry.lazy('netbox_iec62443.graphql.types')]
    broker_zone: Annotated['ZoneType', strawberry.lazy('netbox_iec62443.graphql.types')] | None
    decided_by: Annotated['ContactType', strawberry.lazy('tenancy.graphql.types')] | None
    hops: list[Annotated['FlowHopType', strawberry.lazy('netbox_iec62443.graphql.types')]]
    port_mappings: list[str]
    access: list[str]
    topics: list[str]


@register_type(models.FlowHop, fields='__all__', filters=FlowHopFilter, pagination=True)
class FlowHopType(PrimaryObjectType):
    flow: Annotated['FlowType', strawberry.lazy('netbox_iec62443.graphql.types')]
    device: Annotated['DeviceType', strawberry.lazy('dcim.graphql.types')] | None
    virtual_machine: Annotated['VirtualMachineType', strawberry.lazy('virtualization.graphql.types')] | None
    tunnel: Annotated['TunnelType', strawberry.lazy('vpn.graphql.types')] | None


@register_type(models.Fieldbus, fields='__all__', filters=FieldbusFilter, pagination=True)
class FieldbusType(PrimaryObjectType):
    site: Annotated['SiteType', strawberry.lazy('dcim.graphql.types')] | None
    zone: Annotated['ZoneType', strawberry.lazy('netbox_iec62443.graphql.types')] | None
    gateway: Annotated['DeviceType', strawberry.lazy('dcim.graphql.types')] | None
    services: list[Annotated['IndustrialServiceType', strawberry.lazy('netbox_iec62443.graphql.types')]]


@register_type(models.IndustrialService, fields='__all__', filters=IndustrialServiceFilter, pagination=True)
class IndustrialServiceType(PrimaryObjectType):
    device: Annotated['DeviceType', strawberry.lazy('dcim.graphql.types')] | None
    virtual_machine: Annotated['VirtualMachineType', strawberry.lazy('virtualization.graphql.types')] | None
    service: Annotated['ServiceType', strawberry.lazy('ipam.graphql.types')] | None
    fieldbus: Annotated['FieldbusType', strawberry.lazy('netbox_iec62443.graphql.types')] | None


@register_type(models.RiskAssessment, fields='__all__', filters=RiskAssessmentFilter, pagination=True)
class RiskAssessmentType(PrimaryObjectType):
    zone: Annotated['ZoneType', strawberry.lazy('netbox_iec62443.graphql.types')] | None
    conduit: Annotated['ConduitType', strawberry.lazy('netbox_iec62443.graphql.types')] | None
    assessed_by: Annotated['ContactType', strawberry.lazy('tenancy.graphql.types')] | None
    approved_by: Annotated['ContactType', strawberry.lazy('tenancy.graphql.types')] | None
    requirement_statuses: list[
        Annotated['RequirementStatusType', strawberry.lazy('netbox_iec62443.graphql.types')]
    ]


@register_type(models.SystemRequirement, fields='__all__', filters=SystemRequirementFilter, pagination=True)
class SystemRequirementType(PrimaryObjectType):
    parent: Annotated['SystemRequirementType', strawberry.lazy('netbox_iec62443.graphql.types')] | None
    enhancements: list[Annotated['SystemRequirementType', strawberry.lazy('netbox_iec62443.graphql.types')]]
    statuses: list[Annotated['RequirementStatusType', strawberry.lazy('netbox_iec62443.graphql.types')]]


@register_type(models.RequirementStatus, fields='__all__', filters=RequirementStatusFilter, pagination=True)
class RequirementStatusType(PrimaryObjectType):
    zone: Annotated['ZoneType', strawberry.lazy('netbox_iec62443.graphql.types')] | None
    conduit: Annotated['ConduitType', strawberry.lazy('netbox_iec62443.graphql.types')] | None
    requirement: Annotated['SystemRequirementType', strawberry.lazy('netbox_iec62443.graphql.types')]
    risk_assessment: Annotated['RiskAssessmentType', strawberry.lazy('netbox_iec62443.graphql.types')] | None
    assessed_by: Annotated['ContactType', strawberry.lazy('tenancy.graphql.types')] | None
