from typing import TYPE_CHECKING, Annotated

import strawberry

from netbox.graphql.types import PrimaryObjectType, register_type

from .. import models
from .filters import ConduitFilter, ZoneFilter

if TYPE_CHECKING:
    from dcim.graphql.types import DeviceType, SiteType
    from ipam.graphql.types import PrefixType
    from tenancy.graphql.types import TenantType
    from virtualization.graphql.types import VirtualMachineType

__all__ = ('ConduitType', 'ZoneType')


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
