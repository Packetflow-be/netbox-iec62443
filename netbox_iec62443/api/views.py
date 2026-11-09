from django.conf import settings
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from dcim.api.serializers import SiteSerializer
from dcim.models import Site
from netbox.api.viewsets import NetBoxModelViewSet

from ..accessmap import access_map_conduits, access_map_svg
from ..choices import PurdueLevelChoices

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


class AccessMapAPIView(APIView):
    """
    The access map of one site as data: the conduits into zones at Purdue level <= max_level (not allowed
    first) and the same SVG diagram as the UI. GET ?site_id=<id>[&max_level=<level>]. For report builders.
    """
    queryset = Conduit.objects.all()  # for NetBox's token permission check (view_conduit)

    def get_view_name(self):
        return 'Access map'

    def get(self, request):
        if not request.user.has_perm('netbox_iec62443.view_conduit'):
            raise PermissionDenied()
        default = str(settings.PLUGINS_CONFIG.get('netbox_iec62443', {}).get('access_map_max_level', '2'))
        max_level = request.query_params.get('max_level') or default
        if max_level not in PurdueLevelChoices.values():
            raise ValidationError({'max_level': f'Not a Purdue level: {max_level}'})
        try:
            site = Site.objects.restrict(request.user, 'view').get(pk=int(request.query_params.get('site_id', '')))
        except (ValueError, Site.DoesNotExist):
            raise ValidationError({'site_id': 'A site you can view is required.'})
        conduits = list(access_map_conduits(
            Conduit.objects.restrict(request.user, 'view'), site=site, max_level=max_level,
        ))
        zones = Zone.objects.restrict(request.user, 'view').filter(site=site)
        context = {'request': request}
        return Response({
            'site': SiteSerializer(site, nested=True, context=context).data,
            'max_level': max_level,
            'conduits': ConduitSerializer(conduits, many=True, context=context).data,
            'svg': str(access_map_svg(conduits, zones)),
        })
