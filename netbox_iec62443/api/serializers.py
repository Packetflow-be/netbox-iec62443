from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from dcim.api.serializers import DeviceSerializer, SiteSerializer
from dcim.models import Device
from ipam.api.serializers import PrefixSerializer, ServiceSerializer
from ipam.api.serializers_.services import PortMappingsField
from ipam.models import Prefix
from netbox.api.fields import ChoiceField, SerializedPKRelatedField
from netbox.api.serializers import PrimaryModelSerializer
from tenancy.api.serializers import ContactSerializer, TenantSerializer
from virtualization.api.serializers import VirtualMachineSerializer
from virtualization.models import VirtualMachine
from vpn.api.serializers import TunnelSerializer

from ..choices import (
    AccessChoices,
    FieldbusMediumChoices,
    FlowAllowedChoices,
    FlowProtocolChoices,
    IndustrialProtocolChoices,
    PurdueLevelChoices,
    SecurityLevelChoices,
    ServiceRoleChoices,
    ZoneTypeChoices,
)
from ..models import Conduit, Fieldbus, Flow, FlowHop, IndustrialService, Zone

__all__ = (
    'ConduitSerializer', 'FieldbusSerializer', 'FlowHopSerializer', 'FlowSerializer', 'IndustrialServiceSerializer',
    'ZoneSerializer',
)


class StringChoiceField(ChoiceField):
    """NetBox's ChoiceField turns "1" into 1; Purdue level values are strings ("1", "3.5")."""

    def to_internal_value(self, data):
        if isinstance(data, (int, float)) and not isinstance(data, bool):
            data = str(data)
        if data == '' and self.allow_blank:
            return data
        if isinstance(data, str) and data in self._choices:
            return data
        return super().to_internal_value(data)


class ZoneSerializer(PrimaryModelSerializer):
    site = SiteSerializer(nested=True, required=False, allow_null=True)
    tenant = TenantSerializer(nested=True, required=False, allow_null=True)
    zone_type = ChoiceField(choices=ZoneTypeChoices, required=False)
    purdue_level = StringChoiceField(choices=PurdueLevelChoices, allow_blank=True, required=False)
    security_level_target = ChoiceField(choices=SecurityLevelChoices, allow_null=True, required=False)
    devices = SerializedPKRelatedField(
        queryset=Device.objects.all(), serializer=DeviceSerializer, nested=True,
        required=False, many=True,
    )
    virtual_machines = SerializedPKRelatedField(
        queryset=VirtualMachine.objects.all(), serializer=VirtualMachineSerializer,
        nested=True, required=False, many=True,
    )
    prefixes = SerializedPKRelatedField(
        queryset=Prefix.objects.all(), serializer=PrefixSerializer, nested=True,
        required=False, many=True,
    )

    class Meta:
        model = Zone
        fields = (
            'id', 'url', 'display_url', 'display', 'name', 'slug', 'site', 'tenant', 'zone_type', 'purdue_level',
            'security_level_target', 'devices', 'virtual_machines', 'prefixes', 'description', 'owner',
            'comments', 'tags', 'custom_fields', 'created', 'last_updated',
        )
        brief_fields = ('id', 'url', 'display', 'name', 'slug', 'zone_type', 'purdue_level', 'description')


class ConduitSerializer(PrimaryModelSerializer):
    site = SiteSerializer(nested=True, required=False, allow_null=True)
    zones = SerializedPKRelatedField(
        queryset=Zone.objects.all(), serializer=ZoneSerializer, nested=True, many=True,
    )
    security_level_target = ChoiceField(choices=SecurityLevelChoices, allow_null=True, required=False)
    enforcing_devices = SerializedPKRelatedField(
        queryset=Device.objects.all(), serializer=DeviceSerializer, nested=True, required=False, many=True,
    )
    enforcing_virtual_machines = SerializedPKRelatedField(
        queryset=VirtualMachine.objects.all(), serializer=VirtualMachineSerializer, nested=True, required=False,
        many=True,
    )

    class Meta:
        model = Conduit
        fields = (
            'id', 'url', 'display_url', 'display', 'name', 'site', 'zones', 'security_level_target',
            'enforcing_devices', 'enforcing_virtual_machines', 'description', 'owner', 'comments', 'tags',
            'custom_fields', 'created', 'last_updated',
        )
        brief_fields = ('id', 'url', 'display', 'name', 'description')

    def validate_zones(self, value):
        if len(value) < 2:
            raise serializers.ValidationError('A conduit joins two or more zones.')
        return value


class FlowSerializer(PrimaryModelSerializer):
    conduit = ConduitSerializer(nested=True, required=False, allow_null=True)
    source_zone = ZoneSerializer(nested=True)
    destination_zone = ZoneSerializer(nested=True)
    protocol = ChoiceField(choices=FlowProtocolChoices, allow_blank=True, required=False)
    port_mappings = PortMappingsField(required=False)
    access = serializers.ListField(
        child=serializers.ChoiceField(choices=AccessChoices.values()), required=False,
    )
    allowed = ChoiceField(choices=FlowAllowedChoices, required=False)
    decided_by = ContactSerializer(nested=True, required=False, allow_null=True)
    hops = serializers.SerializerMethodField(read_only=True)
    expired = serializers.BooleanField(source='is_expired', read_only=True)
    review_due = serializers.BooleanField(source='is_review_due', read_only=True)
    stale = serializers.BooleanField(source='is_stale', read_only=True)

    class Meta:
        model = Flow
        fields = (
            'id', 'url', 'display_url', 'display', 'name', 'conduit', 'source_zone', 'destination_zone', 'protocol',
            'port_mappings', 'access', 'remote_access', 'hops', 'allowed', 'decided_by', 'decided_on', 'review_by',
            'expires', 'expired', 'review_due', 'first_seen', 'last_seen', 'stale', 'evidence', 'description',
            'owner', 'comments', 'tags', 'custom_fields', 'created', 'last_updated',
        )
        brief_fields = ('id', 'url', 'display', 'name', 'allowed', 'description')

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_hops(self, obj):
        """The path in order: position, kind (device, virtual-machine, tunnel), id and name of what it runs through."""
        hops = []
        for hop in obj.hops.all():
            target = hop.hop
            kind = 'device' if hop.device_id else 'virtual-machine' if hop.virtual_machine_id else 'tunnel'
            hops.append({'id': hop.pk, 'position': hop.position, 'kind': kind, 'object_id': target.pk,
                         'name': str(target)})
        return hops


class FlowHopSerializer(PrimaryModelSerializer):
    flow = FlowSerializer(nested=True)
    device = DeviceSerializer(nested=True, required=False, allow_null=True)
    virtual_machine = VirtualMachineSerializer(nested=True, required=False, allow_null=True)
    tunnel = TunnelSerializer(nested=True, required=False, allow_null=True)

    class Meta:
        model = FlowHop
        fields = (
            'id', 'url', 'display_url', 'display', 'flow', 'position', 'device', 'virtual_machine', 'tunnel',
            'description', 'owner', 'comments', 'tags', 'custom_fields', 'created', 'last_updated',
        )
        brief_fields = ('id', 'url', 'display', 'position', 'description')


class FieldbusSerializer(PrimaryModelSerializer):
    site = SiteSerializer(nested=True, required=False, allow_null=True)
    zone = ZoneSerializer(nested=True, required=False, allow_null=True)
    medium = ChoiceField(choices=FieldbusMediumChoices)
    protocol = ChoiceField(choices=IndustrialProtocolChoices, allow_blank=True, required=False)
    gateway = DeviceSerializer(nested=True, required=False, allow_null=True)

    class Meta:
        model = Fieldbus
        fields = (
            'id', 'url', 'display_url', 'display', 'name', 'site', 'zone', 'medium', 'protocol', 'gateway',
            'description', 'owner', 'comments', 'tags', 'custom_fields', 'created', 'last_updated',
        )
        brief_fields = ('id', 'url', 'display', 'name', 'medium', 'description')


class IndustrialServiceSerializer(PrimaryModelSerializer):
    device = DeviceSerializer(nested=True, required=False, allow_null=True)
    virtual_machine = VirtualMachineSerializer(nested=True, required=False, allow_null=True)
    protocol = ChoiceField(choices=IndustrialProtocolChoices)
    role = ChoiceField(choices=ServiceRoleChoices, required=False)
    service = ServiceSerializer(nested=True, required=False, allow_null=True)
    fieldbus = FieldbusSerializer(nested=True, required=False, allow_null=True)

    class Meta:
        model = IndustrialService
        fields = (
            'id', 'url', 'display_url', 'display', 'device', 'virtual_machine', 'protocol', 'role', 'service',
            'fieldbus', 'address', 'evidence', 'description', 'owner', 'comments', 'tags', 'custom_fields', 'created',
            'last_updated',
        )
        brief_fields = ('id', 'url', 'display', 'protocol', 'role', 'description')
