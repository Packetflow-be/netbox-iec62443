from django.db.models import Q

from netbox.plugins import PluginTemplateExtension

from .choices import PurdueLevelChoices
from .customfields import get_purdue_level
from .models import Conduit, Fieldbus, IndustrialService, Zone


class AssetIEC62443Panel(PluginTemplateExtension):
    """Shows an asset's Purdue level, its zones and the conduits of those zones."""
    models = ['dcim.device', 'virtualization.virtualmachine']

    def right_page(self):
        obj = self.context['object']
        user = self.context['request'].user
        if not user.has_perm('netbox_iec62443.view_zone'):
            return ''
        zones = list(Zone.objects.restrict(user, 'view').filter(
            Q(devices=obj) if obj._meta.model_name == 'device' else Q(virtual_machines=obj)
        ).select_related('site'))
        conduits = []
        if zones:
            conduits = Conduit.objects.restrict(user, 'view').filter(
                Q(source_zone__in=zones) | Q(destination_zone__in=zones)
            ).select_related('source_zone', 'destination_zone').distinct()
        is_device = obj._meta.model_name == 'device'
        services, bridges = [], []
        if user.has_perm('netbox_iec62443.view_industrialservice'):
            services = IndustrialService.objects.restrict(user, 'view').filter(
                Q(device=obj) if is_device else Q(virtual_machine=obj)
            ).select_related('interface', 'fieldbus')
        if is_device and user.has_perm('netbox_iec62443.view_fieldbus'):
            bridges = Fieldbus.objects.restrict(user, 'view').filter(gateway=obj)
        level = get_purdue_level(obj)
        return self.render('netbox_iec62443/inc/asset_panel.html', extra_context={
            'zones': zones,
            'conduits': conduits,
            'services': services,
            'bridges': bridges,
            'purdue_level': level,
            'purdue_level_label': dict(PurdueLevelChoices.CHOICES).get(level, level),
            'purdue_level_color': PurdueLevelChoices.colors.get(level),
        })


template_extensions = [AssetIEC62443Panel]
