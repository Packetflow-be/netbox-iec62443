from django.conf import settings
from django.db.models import Q
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from dcim.api.serializers import SiteSerializer
from dcim.models import Site
from netbox.api.viewsets import NetBoxModelViewSet

from .. import filtersets
from ..accessmap import access_map_flows
from ..checks import SEVERITIES, run_checks
from ..choices import PurdueLevelChoices
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
from ..overview import build_overview, overview_json
from ..register import build_register, register_json
from ..rules import build_rules
from .serializers import (
    ConduitSerializer,
    FieldbusSerializer,
    FlowHopSerializer,
    FlowSerializer,
    IndustrialServiceSerializer,
    RequirementStatusSerializer,
    RiskAssessmentSerializer,
    SystemRequirementSerializer,
    ZoneSerializer,
)

FLOW_HOPS = ('hops__device', 'hops__virtual_machine', 'hops__tunnel')


class ZoneViewSet(NetBoxModelViewSet):
    queryset = Zone.objects.select_related('parent', 'accountable').prefetch_related(
        'devices', 'virtual_machines', 'prefixes', 'tags')
    serializer_class = ZoneSerializer
    filterset_class = filtersets.ZoneFilterSet


class ConduitViewSet(NetBoxModelViewSet):
    queryset = Conduit.objects.prefetch_related('zones', 'enforcing_devices', 'enforcing_virtual_machines', 'tags')
    serializer_class = ConduitSerializer
    filterset_class = filtersets.ConduitFilterSet


class FlowViewSet(NetBoxModelViewSet):
    queryset = Flow.objects.select_related('conduit', 'source_zone', 'destination_zone', 'broker_zone', 'decided_by') \
        .prefetch_related('tags', *FLOW_HOPS)
    serializer_class = FlowSerializer
    filterset_class = filtersets.FlowFilterSet


class FlowHopViewSet(NetBoxModelViewSet):
    queryset = FlowHop.objects.select_related('flow', 'device', 'virtual_machine', 'tunnel').prefetch_related('tags')
    serializer_class = FlowHopSerializer
    filterset_class = filtersets.FlowHopFilterSet


class SystemRequirementViewSet(NetBoxModelViewSet):
    queryset = SystemRequirement.objects.select_related('parent').prefetch_related('tags')
    serializer_class = SystemRequirementSerializer
    filterset_class = filtersets.SystemRequirementFilterSet


class RequirementStatusViewSet(NetBoxModelViewSet):
    queryset = RequirementStatus.objects.select_related(
        'zone', 'conduit', 'requirement', 'risk_assessment', 'assessed_by',
    ).prefetch_related('tags')
    serializer_class = RequirementStatusSerializer
    filterset_class = filtersets.RequirementStatusFilterSet


class RiskAssessmentViewSet(NetBoxModelViewSet):
    queryset = RiskAssessment.objects.select_related('zone', 'conduit', 'assessed_by', 'approved_by') \
        .prefetch_related('tags')
    serializer_class = RiskAssessmentSerializer
    filterset_class = filtersets.RiskAssessmentFilterSet


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
        if not request.user.has_perm('netbox_ot.view_flow'):
            raise PermissionDenied()
        default = str(settings.PLUGINS_CONFIG.get('netbox_ot', {}).get('access_map_max_level', '2'))
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


def _site(request):
    try:
        return Site.objects.restrict(request.user, 'view').get(pk=int(request.query_params.get('site_id', '')))
    except (ValueError, Site.DoesNotExist):
        raise ValidationError({'site_id': 'A site you can view is required.'})


class ChecksAPIView(APIView):
    """
    Consistency checks of one site as data. GET ?site_id=<id>[&severity=error,warning][&check=<id>,...].
    Findings are limited to the objects you can view.
    """
    queryset = Zone.objects.all()  # for NetBox's token permission check (view_zone)

    def get_view_name(self):
        return 'Consistency checks'

    def get(self, request):
        if not request.user.has_perm('netbox_ot.view_zone'):
            raise PermissionDenied()
        site = _site(request)
        severities = [s for s in request.query_params.get('severity', '').split(',') if s]
        if any(s not in SEVERITIES for s in severities):
            raise ValidationError({'severity': f'One or more of {", ".join(SEVERITIES)}'})
        checks = [c for c in request.query_params.get('check', '').split(',') if c]
        findings = run_checks(site=site, user=request.user, checks=checks or None, severities=severities or None)
        return Response({
            'site': SiteSerializer(site, nested=True, context={'request': request}).data,
            'count': len(findings),
            'findings': [{
                'check': f.check, 'severity': f.severity, 'title': str(f.title), 'message': f.message,
                'object': {'type': f.obj._meta.label_lower, 'id': f.obj.pk, 'display': str(f.obj),
                           'url': request.build_absolute_uri(f.obj.get_absolute_url())},
            } for f in findings],
        })


class RegisterAPIView(APIView):
    """The zone and conduit register of one site (zones, conduits, flows, findings). GET ?site_id=<id>."""
    queryset = Zone.objects.all()  # for NetBox's token permission check (view_zone)

    def get_view_name(self):
        return 'Zone and conduit register'

    def get(self, request):
        if not request.user.has_perm('netbox_ot.view_zone'):
            raise PermissionDenied()
        site = _site(request)
        return Response({
            'site': SiteSerializer(site, nested=True, context={'request': request}).data,
            **register_json(build_register(site, user=request.user)),
        })


class OverviewAPIView(APIView):
    """
    Where a site stands: security levels per foundational requirement (target against achieved), requirement
    statuses, risk assessments and check findings, as numbers. GET ?site_id=<id>[&zone_id=<id>].
    """
    queryset = Zone.objects.all()  # for NetBox's token permission check (view_zone)

    def get_view_name(self):
        return 'OT overview'

    def get(self, request):
        if not request.user.has_perm('netbox_ot.view_zone'):
            raise PermissionDenied()
        site = _site(request)
        zone = None
        if zone_id := request.query_params.get('zone_id'):
            zone = Zone.objects.restrict(request.user, 'view').filter(
                site=site, pk=int(zone_id) if zone_id.isdigit() else 0).first()
            if zone is None:
                raise ValidationError({'zone_id': 'A zone of this site that you can view.'})
        return Response({
            'site': SiteSerializer(site, nested=True, context={'request': request}).data,
            **overview_json(build_overview(site, user=request.user, zone=zone)),
        })


class FirewallRulesAPIView(APIView):
    """
    Vendor-neutral firewall rules from the allowed flows of a site. GET ?site_id=<id>[&device_id=<id> |
    &virtual_machine_id=<id>][&include_denied=true]. Flows without a verdict are counted in not_exported.
    """
    queryset = Flow.objects.all()  # for NetBox's token permission check (view_flow)

    def get_view_name(self):
        return 'Firewall rules'

    def get(self, request):
        from dcim.models import Device
        from virtualization.models import VirtualMachine

        if not request.user.has_perm('netbox_ot.view_flow'):
            raise PermissionDenied()
        site = _site(request)
        enforcer = None
        for param, model in (('device_id', Device), ('virtual_machine_id', VirtualMachine)):
            if request.query_params.get(param):
                try:
                    enforcer = model.objects.restrict(request.user, 'view').get(pk=int(request.query_params[param]))
                except (ValueError, model.DoesNotExist):
                    raise ValidationError({param: 'Not found.'})
        flows = Flow.objects.restrict(request.user, 'view').filter(
            Q(source_zone__site=site) | Q(destination_zone__site=site))
        include_denied = request.query_params.get('include_denied', '').lower() in ('1', 'true', 'yes')
        rules, skipped = build_rules(flows, enforced_by=enforcer, include_denied=include_denied)
        return Response({
            'site': SiteSerializer(site, nested=True, context={'request': request}).data,
            'rules': rules,
            'not_exported': dict(skipped),
        })
