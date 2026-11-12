from django.db.models import Q

from netbox.plugins import PluginTemplateExtension

from . import lifecycle
from .accessmap import verdict_order
from .choices import PurdueLevelChoices
from .customfields import get_firmware_version, get_purdue_level
from .models import Conduit, Fieldbus, Flow, IndustrialService, Zone

PANEL_FLOWS = 20


class AssetOTPanel(PluginTemplateExtension):
    """Shows an asset's Purdue level, its zones and their flows, its services, and the conduits and flows it carries."""
    models = ['dcim.device', 'virtualization.virtualmachine']

    def right_page(self):
        obj = self.context['object']
        user = self.context['request'].user
        if not user.has_perm('netbox_ot.view_zone'):
            return ''
        is_device = obj._meta.model_name == 'device'
        zones = list(Zone.objects.restrict(user, 'view').filter(
            Q(devices=obj) if is_device else Q(virtual_machines=obj)
        ).select_related('site'))
        flows, flow_count, hop_flows = [], 0, []
        if user.has_perm('netbox_ot.view_flow'):
            visible = Flow.objects.restrict(user, 'view')
            if zones:
                zone_flows = visible.filter(Q(source_zone__in=zones) | Q(destination_zone__in=zones))
                flow_count = zone_flows.count()
                flows = zone_flows.select_related('source_zone', 'destination_zone').annotate(
                    verdict_order=verdict_order()).order_by('verdict_order', 'name')[:PANEL_FLOWS]
            hop_filter = Q(hops__device=obj) if is_device else Q(hops__virtual_machine=obj)
            hop_flows = visible.filter(hop_filter).distinct()
        enforced = []
        if user.has_perm('netbox_ot.view_conduit'):
            enforced = Conduit.objects.restrict(user, 'view').filter(
                Q(enforcing_devices=obj) if is_device else Q(enforcing_virtual_machines=obj)
            )
        services, bridges = [], []
        if user.has_perm('netbox_ot.view_industrialservice'):
            services = IndustrialService.objects.restrict(user, 'view').filter(
                Q(device=obj) if is_device else Q(virtual_machine=obj)
            ).select_related('service', 'fieldbus')
        if is_device and user.has_perm('netbox_ot.view_fieldbus'):
            bridges = Fieldbus.objects.restrict(user, 'view').filter(gateway=obj)
        level = get_purdue_level(obj)
        firmware, end = '', None
        if is_device:
            firmware = get_firmware_version(obj)
            end = lifecycle.end_of_support([obj]).get(obj.pk)
        return self.render('netbox_ot/inc/asset_panel.html', extra_context={
            'zones': zones,
            'flows': flows,
            'flow_count': flow_count,
            'hop_flows': hop_flows,
            'enforced': enforced,
            'services': services,
            'bridges': bridges,
            'purdue_level': level,
            'firmware': firmware,
            'end_of_support': end,
            'lifecycle_installed': is_device and lifecycle.installed(),
            'purdue_level_label': dict(PurdueLevelChoices.CHOICES).get(level, level),
            'purdue_level_color': PurdueLevelChoices.colors.get(level),
        })


template_extensions = [AssetOTPanel]
