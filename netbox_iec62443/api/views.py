from django.conf import settings
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from dcim.api.serializers import SiteSerializer
from dcim.models import Site
from netbox.api.viewsets import NetBoxModelViewSet

from .. import filtersets
from ..accessmap import access_map_flows
from ..choices import PurdueLevelChoices
from ..models import Conduit, Fieldbus, Flow, FlowHop, IndustrialService, Zone
from .serializers import (
    ConduitSerializer,
    FieldbusSerializer,
    FlowHopSerializer,
    FlowSerializer,
    IndustrialServiceSerializer,
    ZoneSerializer,
)

FLOW_HOPS = ('hops__device', 'hops__virtual_machine', 'hops__tunnel')


class ZoneViewSet(NetBoxModelViewSet):
    queryset = Zone.objects.prefetch_related('devices', 'virtual_machines', 'prefixes', 'tags')
    serializer_class = ZoneSerializer
    filterset_class = filtersets.ZoneFilterSet


class ConduitViewSet(NetBoxModelViewSet):
    queryset = Conduit.objects.prefetch_related('zones', 'enforcing_devices', 'enforcing_virtual_machines', 'tags')
    serializer_class = ConduitSerializer
    filterset_class = filtersets.ConduitFilterSet


class FlowViewSet(NetBoxModelViewSet):
    queryset = Flow.objects.select_related('conduit', 'source_zone', 'destination_zone', 'decided_by') \
        .prefetch_related('tags', *FLOW_HOPS)
    serializer_class = FlowSerializer
    filterset_class = filtersets.FlowFilterSet


class FlowHopViewSet(NetBoxModelViewSet):
    queryset = FlowHop.objects.select_related('flow', 'device', 'virtual_machine', 'tunnel').prefetch_related('tags')
    serializer_class = FlowHopSerializer
    filterset_class = filtersets.FlowHopFilterSet


class FieldbusViewSet(NetBoxModelViewSet):
    queryset = Fieldbus.objects.select_related('site', 'zone', 'gateway').prefetch_related('tags')
    serializer_class = FieldbusSerializer
    filterset_class = filtersets.FieldbusFilterSet


class IndustrialServiceViewSet(NetBoxModelViewSet):
    queryset = IndustrialService.objects.select_related(
        'device', 'virtual_machine', 'service', 'fieldbus',
    ).prefetch_related('tags')
    serializer_class = IndustrialServiceSerializer
    filterset_class = filtersets.IndustrialServiceFilterSet


class AccessMapAPIView(APIView):
    """
    The access map of one site as data: the flows into zones at Purdue level <= max_level, not allowed first, then
    allowed but expired, unknown, allowed. GET ?site_id=<id>[&max_level=<level>]. For reports and other tools.
    """
    queryset = Flow.objects.all()  # for NetBox's token permission check (view_flow)

    def get_view_name(self):
        return 'Access map'

    def get(self, request):
        if not request.user.has_perm('netbox_iec62443.view_flow'):
            raise PermissionDenied()
        default = str(settings.PLUGINS_CONFIG.get('netbox_iec62443', {}).get('access_map_max_level', '2'))
        max_level = request.query_params.get('max_level') or default
        if max_level not in PurdueLevelChoices.values():
            raise ValidationError({'max_level': f'Not a Purdue level: {max_level}'})
        try:
            site = Site.objects.restrict(request.user, 'view').get(pk=int(request.query_params.get('site_id', '')))
        except (ValueError, Site.DoesNotExist):
            raise ValidationError({'site_id': 'A site you can view is required.'})
        flows = access_map_flows(Flow.objects.restrict(request.user, 'view'), site=site, max_level=max_level)
        context = {'request': request}
        return Response({
            'site': SiteSerializer(site, nested=True, context=context).data,
            'max_level': max_level,
            'flows': FlowSerializer(flows, many=True, context=context).data,
        })
