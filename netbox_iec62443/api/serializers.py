from rest_framework import serializers

from dcim.api.serializers import DeviceSerializer, InterfaceSerializer, SiteSerializer
from dcim.models import Device
from ipam.api.serializers import PrefixSerializer
from ipam.models import Prefix
from netbox.api.fields import ChoiceField, SerializedPKRelatedField
from netbox.api.serializers import PrimaryModelSerializer
from tenancy.api.serializers import TenantSerializer
from virtualization.api.serializers import VirtualMachineSerializer
from virtualization.models import VirtualMachine

from ..choices import (
    ConduitAllowedChoices,
    ConduitDirectionChoices,
    FieldbusMediumChoices,
    IndustrialProtocolChoices,
    PurdueLevelChoices,
    SecurityLevelChoices,
    ServiceRoleChoices,
)
from ..models import Conduit, Fieldbus, IndustrialService, Zone

__all__ = ('ConduitSerializer', 'FieldbusSerializer', 'IndustrialServiceSerializer', 'ZoneSerializer')


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
            'id', 'url', 'display_url', 'display', 'name', 'slug', 'site', 'tenant', 'purdue_level',
            'security_level_target', 'devices', 'virtual_machines', 'prefixes', 'description', 'owner',
            'comments', 'tags', 'custom_fields', 'created', 'last_updated',
        )
        brief_fields = ('id', 'url', 'display', 'name', 'slug', 'purdue_level', 'description')


class ConduitSerializer(PrimaryModelSerializer):
    source_zone = ZoneSerializer(nested=True)
    destination_zone = ZoneSerializer(nested=True)
    direction = ChoiceField(choices=ConduitDirectionChoices, required=False)
    allowed = ChoiceField(choices=ConduitAllowedChoices, required=False)

    class Meta:
        model = Conduit
        fields = (
            'id', 'url', 'display_url', 'display', 'name', 'source_zone', 'destination_zone', 'direction',
            'allowed', 'protocols', 'remote_access', 'via', 'evidence', 'description', 'owner', 'comments',
            'tags', 'custom_fields', 'created', 'last_updated',
        )
        brief_fields = ('id', 'url', 'display', 'name', 'allowed', 'description')


class FieldbusSerializer(PrimaryModelSerializer):
    site = SiteSerializer(nested=True, required=False, allow_null=True)
    zone = ZoneSerializer(nested=True, required=False, allow_null=True)
    medium = ChoiceField(choices=FieldbusMediumChoices)
    protocol = ChoiceField(choices=IndustrialProtocolChoices, allow_blank=True, required=False)
    gateway = DeviceSerializer(nested=True, required=False, allow_null=True)

    class Meta:
        model = Fieldbus
        fields = (
            'id', 'url', 'display_url', 'display', 'name', 'site', 'zone', 'medium', 'protocol', 'baud_rate',
            'frame_format', 'gateway', 'description', 'owner', 'comments', 'tags', 'custom_fields', 'created',
            'last_updated',
        )
        brief_fields = ('id', 'url', 'display', 'name', 'medium', 'description')


class IndustrialServiceSerializer(PrimaryModelSerializer):
    device = DeviceSerializer(nested=True, required=False, allow_null=True)
    virtual_machine = VirtualMachineSerializer(nested=True, required=False, allow_null=True)
    protocol = ChoiceField(choices=IndustrialProtocolChoices)
    role = ChoiceField(choices=ServiceRoleChoices, required=False)
    interface = InterfaceSerializer(nested=True, required=False, allow_null=True)
    ports = serializers.ListField(
        child=serializers.IntegerField(min_value=1, max_value=65535), required=False,
    )
    fieldbus = FieldbusSerializer(nested=True, required=False, allow_null=True)

    class Meta:
        model = IndustrialService
        fields = (
            'id', 'url', 'display_url', 'display', 'device', 'virtual_machine', 'protocol', 'role', 'interface',
            'ports', 'fieldbus', 'address', 'evidence', 'description', 'owner', 'comments', 'tags',
            'custom_fields', 'created', 'last_updated',
        )
        brief_fields = ('id', 'url', 'display', 'protocol', 'role', 'description')
