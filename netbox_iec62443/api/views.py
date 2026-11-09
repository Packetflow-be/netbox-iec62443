from netbox.api.viewsets import NetBoxModelViewSet

from .. import filtersets
from ..models import Conduit, Fieldbus, IndustrialService, Zone
from .serializers import ConduitSerializer, FieldbusSerializer, IndustrialServiceSerializer, ZoneSerializer


class ZoneViewSet(NetBoxModelViewSet):
    queryset = Zone.objects.prefetch_related('devices', 'virtual_machines', 'prefixes', 'tags')
    serializer_class = ZoneSerializer
    filterset_class = filtersets.ZoneFilterSet


class ConduitViewSet(NetBoxModelViewSet):
    queryset = Conduit.objects.select_related('source_zone', 'destination_zone').prefetch_related('tags')
    serializer_class = ConduitSerializer
    filterset_class = filtersets.ConduitFilterSet


class FieldbusViewSet(NetBoxModelViewSet):
    queryset = Fieldbus.objects.select_related('site', 'zone', 'gateway').prefetch_related('tags')
    serializer_class = FieldbusSerializer
    filterset_class = filtersets.FieldbusFilterSet


class IndustrialServiceViewSet(NetBoxModelViewSet):
    queryset = IndustrialService.objects.select_related(
        'device', 'virtual_machine', 'interface', 'fieldbus',
    ).prefetch_related('tags')
    serializer_class = IndustrialServiceSerializer
    filterset_class = filtersets.IndustrialServiceFilterSet
