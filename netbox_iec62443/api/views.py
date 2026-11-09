from netbox.api.viewsets import NetBoxModelViewSet

from .. import filtersets
from ..models import Conduit, Zone
from .serializers import ConduitSerializer, ZoneSerializer


class ZoneViewSet(NetBoxModelViewSet):
    queryset = Zone.objects.prefetch_related('devices', 'virtual_machines', 'prefixes', 'tags')
    serializer_class = ZoneSerializer
    filterset_class = filtersets.ZoneFilterSet


class ConduitViewSet(NetBoxModelViewSet):
    queryset = Conduit.objects.select_related('source_zone', 'destination_zone').prefetch_related('tags')
    serializer_class = ConduitSerializer
    filterset_class = filtersets.ConduitFilterSet
