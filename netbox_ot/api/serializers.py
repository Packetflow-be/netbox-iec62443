from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from dcim.api.serializers import DeviceSerializer, SiteSerializer
from dcim.models import Device
from ipam.api.serializers import PrefixSerializer
from ipam.api.serializers_.services import PortMappingsField
from ipam.models import Prefix, Service
from netbox.api.fields import ChoiceField, SerializedPKRelatedField
from netbox.api.serializers import PrimaryModelSerializer, WritableNestedSerializer
from tenancy.api.serializers import ContactSerializer, TenantSerializer
from virtualization.api.serializers import VirtualMachineSerializer
from virtualization.models import VirtualMachine
from vpn.api.serializers import TunnelSerializer

from ..choices import (
    AccessChoices,
    ConnectionChoices,
    FieldbusMediumChoices,
    FlowAllowedChoices,
    FlowProtocolChoices,
    FoundationalRequirementChoices,
    IndustrialProtocolChoices,
    PurdueLevelChoices,
    RequirementEditionChoices,
    RequirementStatusChoices,
    RiskAssessmentKindChoices,
    RiskAssessmentStatusChoices,
    RiskLevelChoices,
    ServiceRoleChoices,
    ZoneTypeChoices,
)
from ..models import (
    Conduit,
    Fieldbus,
    Flow,
    FlowHop,
    IndustrialService,
    RequirementStatus,
    RiskAssessment,
    SystemRequirement,
    Zone,
)

__all__ = (
    'ConduitSerializer', 'FieldbusSerializer', 'FlowHopSerializer', 'FlowSerializer', 'IndustrialServiceSerializer',
    'RequirementStatusSerializer', 'RiskAssessmentSerializer', 'SystemRequirementSerializer', 'ZoneSerializer',
)


class SecurityLevelVectorField(serializers.ListField):
    """A security level vector: seven levels 0-4 in FR order (IAC, UC, SI, DC, RDF, TRE, RA), or null."""

    def __init__(self, **kwargs):
        kwargs.setdefault('child', serializers.IntegerField(min_value=0, max_value=4))
        kwargs.setdefault('min_length', 7)
        kwargs.setdefault('max_length', 7)
        kwargs.setdefault('allow_null', True)
        kwargs.setdefault('required', False)
        super().__init__(**kwargs)


class NestedServiceSerializer(WritableNestedSerializer):
    """
    A NetBox application service, nested. Our own rather than ipam's ServiceSerializer(nested=True): NetBox 4.7.0's
    validates nested writes as if they were the full serializer and fails.
    """
    port_mappings = serializers.ListField(child=serializers.CharField(), read_only=True)

    class Meta:
        model = Service
        fields = ('id', 'url', 'display_url', 'display', 'name', 'port_mappings', 'description')


class NestedZoneSerializer(WritableNestedSerializer):

    class Meta:
        model = Zone
        fields = ('id', 'url', 'display_url', 'display', 'name', 'slug')


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
    parent = NestedZoneSerializer(required=False, allow_null=True)
    sl_target = SecurityLevelVectorField()
    sl_achieved = SecurityLevelVectorField()
    accountable = ContactSerializer(nested=True, required=False, allow_null=True)
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
            'parent', 'sl_target', 'sl_achieved', 'accountable', 'wireless', 'temporary_devices', 'devices',
            'virtual_machines', 'prefixes', 'description', 'owner', 'comments', 'tags', 'custom_fields', 'created',
            'last_updated',
        )
        brief_fields = ('id', 'url', 'display', 'name', 'slug', 'site', 'zone_type', 'purdue_level', 'description')


class ConduitSerializer(PrimaryModelSerializer):
    site = SiteSerializer(nested=True, required=False, allow_null=True)
    zones = SerializedPKRelatedField(
        queryset=Zone.objects.all(), serializer=ZoneSerializer, nested=True, many=True,
    )
    sl_target = SecurityLevelVectorField()
    sl_achieved = SecurityLevelVectorField()
    accountable = ContactSerializer(nested=True, required=False, allow_null=True)
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
            'id', 'url', 'display_url', 'display', 'name', 'site', 'zones', 'sl_target', 'sl_achieved', 'accountable',
            'enforcing_devices', 'enforcing_virtual_machines', 'description', 'owner', 'comments', 'tags',
            'custom_fields', 'created', 'last_updated',
        )
        brief_fields = ('id', 'url', 'display', 'name', 'site', 'description')

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
    connection = ChoiceField(choices=ConnectionChoices, required=False)
    broker_zone = ZoneSerializer(nested=True, required=False, allow_null=True)
    topics = serializers.ListField(child=serializers.CharField(max_length=255), required=False)
    allowed = ChoiceField(choices=FlowAllowedChoices, required=False)
    decided_by = ContactSerializer(nested=True, required=False, allow_null=True)
    hops = serializers.SerializerMethodField(read_only=True)
    expired = serializers.BooleanField(source='is_expired', read_only=True)
    review_due = serializers.BooleanField(source='is_review_due', read_only=True)
    stale = serializers.BooleanField(source='is_stale', read_only=True)

    class Meta:
        model = Flow
        fields = (
            'id', 'url', 'display_url', 'display', 'name', 'conduit', 'source_zone', 'destination_zone', 'connection',
            'broker_zone', 'topics', 'protocol', 'port_mappings', 'access', 'remote_access', 'hops', 'allowed',
            'decided_by', 'decided_on', 'review_by', 'expires', 'expired', 'review_due', 'first_seen', 'last_seen',
            'stale', 'evidence', 'description', 'owner', 'comments', 'tags', 'custom_fields', 'created', 'last_updated',
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
    service = NestedServiceSerializer(required=False, allow_null=True)
    fieldbus = FieldbusSerializer(nested=True, required=False, allow_null=True)

    class Meta:
        model = IndustrialService
        fields = (
            'id', 'url', 'display_url', 'display', 'device', 'virtual_machine', 'protocol', 'role', 'service',
            'fieldbus', 'address', 'evidence', 'description', 'owner', 'comments', 'tags', 'custom_fields', 'created',
            'last_updated',
        )
        brief_fields = ('id', 'url', 'display', 'protocol', 'role', 'description')


class RiskAssessmentSerializer(PrimaryModelSerializer):
    zone = ZoneSerializer(nested=True, required=False, allow_null=True)
    conduit = ConduitSerializer(nested=True, required=False, allow_null=True)
    kind = ChoiceField(choices=RiskAssessmentKindChoices, required=False)
    status = ChoiceField(choices=RiskAssessmentStatusChoices, required=False)
    assessed_by = ContactSerializer(nested=True, required=False, allow_null=True)
    approved_by = ContactSerializer(nested=True, required=False, allow_null=True)
    unmitigated_risk = ChoiceField(choices=RiskLevelChoices, allow_blank=True, required=False)
    residual_risk = ChoiceField(choices=RiskLevelChoices, allow_blank=True, required=False)
    tolerable_risk = ChoiceField(choices=RiskLevelChoices, allow_blank=True, required=False)
    residual_above_tolerable = serializers.BooleanField(read_only=True)
    current_step = serializers.CharField(read_only=True)

    class Meta:
        model = RiskAssessment
        fields = (
            'id', 'url', 'display_url', 'display', 'zone', 'conduit', 'kind', 'status', 'assessed_on', 'assessed_by',
            'approved_on', 'approved_by', 'next_review', 'method', 'document', 'threats', 'vulnerabilities',
            'consequences', 'unmitigated_likelihood', 'unmitigated_impact', 'unmitigated_risk', 'countermeasures',
            'residual_likelihood', 'residual_impact', 'residual_risk', 'tolerable_risk',
            'residual_above_tolerable', 'current_step', 'description', 'owner', 'comments', 'tags', 'custom_fields',
            'created', 'last_updated',
        )
        brief_fields = ('id', 'url', 'display', 'kind', 'status', 'assessed_on', 'description')


class SystemRequirementSerializer(PrimaryModelSerializer):
    edition = ChoiceField(choices=RequirementEditionChoices, required=False)
    foundational_requirement = ChoiceField(choices=FoundationalRequirementChoices, read_only=True)
    security_level = serializers.IntegerField(min_value=1, max_value=4, required=False, allow_null=True)

    class Meta:
        model = SystemRequirement
        fields = (
            'id', 'url', 'display_url', 'display', 'edition', 'identifier', 'foundational_requirement', 'parent',
            'security_level', 'wording', 'description', 'owner', 'comments', 'tags', 'custom_fields',
            'created', 'last_updated',
        )
        brief_fields = ('id', 'url', 'display', 'edition', 'identifier', 'description')


# The requirement an enhancement belongs to, nested like any other related object (a serializer cannot name itself
# in its own class body)
SystemRequirementSerializer._declared_fields['parent'] = SystemRequirementSerializer(
    nested=True, required=False, allow_null=True,
)


class RequirementStatusSerializer(PrimaryModelSerializer):
    zone = ZoneSerializer(nested=True, required=False, allow_null=True)
    conduit = ConduitSerializer(nested=True, required=False, allow_null=True)
    requirement = SystemRequirementSerializer(nested=True)
    status = ChoiceField(choices=RequirementStatusChoices)
    risk_assessment = RiskAssessmentSerializer(nested=True, required=False, allow_null=True)
    assessed_by = ContactSerializer(nested=True, required=False, allow_null=True)

    class Meta:
        model = RequirementStatus
        fields = (
            'id', 'url', 'display_url', 'display', 'zone', 'conduit', 'requirement', 'status', 'countermeasure',
            'evidence', 'risk_assessment', 'assessed_by', 'assessed_on', 'description', 'owner', 'comments', 'tags',
            'custom_fields', 'created', 'last_updated',
        )
        brief_fields = ('id', 'url', 'display', 'status', 'description')
