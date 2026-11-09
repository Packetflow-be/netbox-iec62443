from typing import TYPE_CHECKING, Annotated

import strawberry

from netbox.graphql.types import PrimaryObjectType, register_type

from .. import models
from .filters import ConduitFilter, FieldbusFilter, IndustrialServiceFilter, ZoneFilter

if TYPE_CHECKING:
    from dcim.graphql.types import DeviceType, InterfaceType, SiteType
    from ipam.graphql.types import PrefixType
    from tenancy.graphql.types import TenantType
    from virtualization.graphql.types import VirtualMachineType

__all__ = ('ConduitType', 'FieldbusType', 'IndustrialServiceType', 'ZoneType')


@register_type(models.Zone, fields='__all__', filters=ZoneFilter, pagination=True)
class ZoneType(PrimaryObjectType):
    site: Annotated['SiteType', strawberry.lazy('dcim.graphql.types')] | None
    tenant: Annotated['TenantType', strawberry.lazy('tenancy.graphql.types')] | None
    devices: list[Annotated['DeviceType', strawberry.lazy('dcim.graphql.types')]]
    virtual_machines: list[Annotated['VirtualMachineType', strawberry.lazy('virtualization.graphql.types')]]
    prefixes: list[Annotated['PrefixType', strawberry.lazy('ipam.graphql.types')]]
    conduits_out: list[Annotated['ConduitType', strawberry.lazy('netbox_iec62443.graphql.types')]]
    conduits_in: list[Annotated['ConduitType', strawberry.lazy('netbox_iec62443.graphql.types')]]


@register_type(models.Conduit, fields='__all__', filters=ConduitFilter, pagination=True)
class ConduitType(PrimaryObjectType):
    source_zone: Annotated['ZoneType', strawberry.lazy('netbox_iec62443.graphql.types')]
    destination_zone: Annotated['ZoneType', strawberry.lazy('netbox_iec62443.graphql.types')]


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
    interface: Annotated['InterfaceType', strawberry.lazy('dcim.graphql.types')] | None
    fieldbus: Annotated['FieldbusType', strawberry.lazy('netbox_iec62443.graphql.types')] | None
    ports: list[int]
