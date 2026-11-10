from django.db.models import Count, Q
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _
from django.views.generic import View

from dcim.models import Site
from extras.ui.panels import CustomFieldsPanel, TagsPanel
from netbox.ui import attrs, layout, panels
from netbox.views import generic
from utilities.views import ContentTypePermissionRequiredMixin, ViewTab, register_model_view

from . import filtersets, forms, tables
from .accessmap import access_map_conduits, access_map_svg
from .choices import PurdueLevelChoices
from .models import Conduit, Fieldbus, IndustrialService, Zone


def _default_max_level():
    from django.conf import settings
    return str(settings.PLUGINS_CONFIG.get('netbox_iec62443', {}).get('access_map_max_level', '2'))


def _ids_or_none(queryset):
    # An empty id list would mean "no filter" (all objects); [0] matches nothing.
    return list(queryset.values_list('pk', flat=True)) or [0]


#
# Panels
#

class ZonePanel(panels.ObjectAttributesPanel):
    name = attrs.TextAttr('name')
    site = attrs.RelatedObjectAttr('site', linkify=True)
    purdue_level = attrs.ChoiceAttr('purdue_level', label=_('Purdue level'))
    security_level_target = attrs.ChoiceAttr('security_level_target', label=_('Security level target (SL-T)'))
    tenant = attrs.RelatedObjectAttr('tenant', linkify=True, grouped_by='group')
    description = attrs.TextAttr('description')


class ConduitPanel(panels.ObjectAttributesPanel):
    name = attrs.TextAttr('name')
    source_zone = attrs.RelatedObjectAttr('source_zone', linkify=True, label=_('From zone'))
    destination_zone = attrs.RelatedObjectAttr('destination_zone', linkify=True, label=_('To zone'))
    direction = attrs.ChoiceAttr('direction')
    description = attrs.TextAttr('description')


class ConduitAccessPanel(panels.ObjectAttributesPanel):
    allowed = attrs.ChoiceAttr('allowed', label=_('Allowed'))
    protocols = attrs.TextAttr('protocols', label=_('Protocols / ports'))
    remote_access = attrs.BooleanAttr('remote_access', label=_('Remote access'))
    via = attrs.TextAttr('via')


#
# Zones
#

@register_model_view(Zone, 'list', path='', detail=False)
class ZoneListView(generic.ObjectListView):
    queryset = Zone.objects.annotate(
        device_count=Count('devices', distinct=True),
        conduit_count=Count('conduits_out', distinct=True) + Count('conduits_in', distinct=True),
    )
    filterset = filtersets.ZoneFilterSet
    filterset_form = forms.ZoneFilterForm
    table = tables.ZoneTable


@register_model_view(Zone)
class ZoneView(generic.ObjectView):
    queryset = Zone.objects.all()
    template_name = 'generic/object.html'
    layout = layout.SimpleLayout(
        left_panels=[
            ZonePanel(),
            TagsPanel(),
        ],
        right_panels=[
            CustomFieldsPanel(),
            panels.CommentsPanel(),
        ],
        bottom_panels=[
            panels.ObjectsTablePanel(
                'netbox_iec62443.conduit',
                filters={'zone_id': lambda ctx: ctx['object'].pk},
                title=_('Conduits'),
            ),
            panels.ObjectsTablePanel(
                'dcim.device',
                filters={'id': lambda ctx: _ids_or_none(ctx['object'].devices.all())},
                title=_('Devices'),
            ),
            panels.ObjectsTablePanel(
                'virtualization.virtualmachine',
                filters={'id': lambda ctx: _ids_or_none(ctx['object'].virtual_machines.all())},
                title=_('Virtual machines'),
            ),
            panels.ObjectsTablePanel(
                'ipam.prefix',
                filters={'id': lambda ctx: _ids_or_none(ctx['object'].prefixes.all())},
                title=_('Prefixes'),
            ),
        ],
    )


@register_model_view(Zone, 'add', detail=False)
@register_model_view(Zone, 'edit')
class ZoneEditView(generic.ObjectEditView):
    queryset = Zone.objects.all()
    form = forms.ZoneForm


@register_model_view(Zone, 'delete')
class ZoneDeleteView(generic.ObjectDeleteView):
    queryset = Zone.objects.all()


@register_model_view(Zone, 'bulk_import', path='import', detail=False)
class ZoneBulkImportView(generic.BulkImportView):
    queryset = Zone.objects.all()
    model_form = forms.ZoneImportForm


@register_model_view(Zone, 'bulk_edit', path='edit', detail=False)
class ZoneBulkEditView(generic.BulkEditView):
    queryset = Zone.objects.all()
    filterset = filtersets.ZoneFilterSet
    table = tables.ZoneTable
    form = forms.ZoneBulkEditForm


@register_model_view(Zone, 'bulk_delete', path='delete', detail=False)
class ZoneBulkDeleteView(generic.BulkDeleteView):
    queryset = Zone.objects.all()
    filterset = filtersets.ZoneFilterSet
    table = tables.ZoneTable


#
# Conduits
#

@register_model_view(Conduit, 'list', path='', detail=False)
class ConduitListView(generic.ObjectListView):
    queryset = Conduit.objects.select_related('source_zone', 'destination_zone')
    filterset = filtersets.ConduitFilterSet
    filterset_form = forms.ConduitFilterForm
    table = tables.ConduitTable


@register_model_view(Conduit)
class ConduitView(generic.ObjectView):
    queryset = Conduit.objects.all()
    template_name = 'generic/object.html'
    layout = layout.SimpleLayout(
        left_panels=[
            ConduitPanel(),
            ConduitAccessPanel(title=_('Access')),
            TagsPanel(),
        ],
        right_panels=[
            panels.TextCodePanel('evidence', title=_('Evidence')),
            CustomFieldsPanel(),
            panels.CommentsPanel(),
        ],
    )


@register_model_view(Conduit, 'add', detail=False)
@register_model_view(Conduit, 'edit')
class ConduitEditView(generic.ObjectEditView):
    queryset = Conduit.objects.all()
    form = forms.ConduitForm


@register_model_view(Conduit, 'delete')
class ConduitDeleteView(generic.ObjectDeleteView):
    queryset = Conduit.objects.all()


@register_model_view(Conduit, 'bulk_import', path='import', detail=False)
class ConduitBulkImportView(generic.BulkImportView):
    queryset = Conduit.objects.all()
    model_form = forms.ConduitImportForm


@register_model_view(Conduit, 'bulk_edit', path='edit', detail=False)
class ConduitBulkEditView(generic.BulkEditView):
    queryset = Conduit.objects.all()
    filterset = filtersets.ConduitFilterSet
    table = tables.ConduitTable
    form = forms.ConduitBulkEditForm


@register_model_view(Conduit, 'bulk_delete', path='delete', detail=False)
class ConduitBulkDeleteView(generic.BulkDeleteView):
    queryset = Conduit.objects.all()
    filterset = filtersets.ConduitFilterSet
    table = tables.ConduitTable


#
# Fieldbuses
#

class FieldbusPanel(panels.ObjectAttributesPanel):
    name = attrs.TextAttr('name')
    site = attrs.RelatedObjectAttr('site', linkify=True)
    zone = attrs.RelatedObjectAttr('zone', linkify=True)
    medium = attrs.ChoiceAttr('medium')
    protocol = attrs.ChoiceAttr('protocol')
    gateway = attrs.RelatedObjectAttr('gateway', linkify=True)
    description = attrs.TextAttr('description')


@register_model_view(Fieldbus, 'list', path='', detail=False)
class FieldbusListView(generic.ObjectListView):
    queryset = Fieldbus.objects.annotate(service_count=Count('services'))
    filterset = filtersets.FieldbusFilterSet
    filterset_form = forms.FieldbusFilterForm
    table = tables.FieldbusTable


@register_model_view(Fieldbus)
class FieldbusView(generic.ObjectView):
    queryset = Fieldbus.objects.all()
    template_name = 'generic/object.html'
    layout = layout.SimpleLayout(
        left_panels=[FieldbusPanel(), TagsPanel()],
        right_panels=[CustomFieldsPanel(), panels.CommentsPanel()],
        bottom_panels=[
            panels.ObjectsTablePanel(
                'netbox_iec62443.industrialservice',
                filters={'fieldbus_id': lambda ctx: ctx['object'].pk},
                title=_('Services on this bus'),
            ),
        ],
    )


@register_model_view(Fieldbus, 'add', detail=False)
@register_model_view(Fieldbus, 'edit')
class FieldbusEditView(generic.ObjectEditView):
    queryset = Fieldbus.objects.all()
    form = forms.FieldbusForm


@register_model_view(Fieldbus, 'delete')
class FieldbusDeleteView(generic.ObjectDeleteView):
    queryset = Fieldbus.objects.all()


@register_model_view(Fieldbus, 'bulk_import', path='import', detail=False)
class FieldbusBulkImportView(generic.BulkImportView):
    queryset = Fieldbus.objects.all()
    model_form = forms.FieldbusImportForm


@register_model_view(Fieldbus, 'bulk_edit', path='edit', detail=False)
class FieldbusBulkEditView(generic.BulkEditView):
    queryset = Fieldbus.objects.all()
    filterset = filtersets.FieldbusFilterSet
    table = tables.FieldbusTable
    form = forms.FieldbusBulkEditForm


@register_model_view(Fieldbus, 'bulk_delete', path='delete', detail=False)
class FieldbusBulkDeleteView(generic.BulkDeleteView):
    queryset = Fieldbus.objects.all()
    filterset = filtersets.FieldbusFilterSet
    table = tables.FieldbusTable


#
# Industrial services
#

class IndustrialServicePanel(panels.ObjectAttributesPanel):
    device = attrs.RelatedObjectAttr('device', linkify=True)
    virtual_machine = attrs.RelatedObjectAttr('virtual_machine', linkify=True, label=_('Virtual machine'))
    protocol = attrs.ChoiceAttr('protocol')
    role = attrs.ChoiceAttr('role')
    interface = attrs.RelatedObjectAttr('interface', linkify=True)
    ports = attrs.TextAttr('ports_display', label=_('Ports'))
    fieldbus = attrs.RelatedObjectAttr('fieldbus', linkify=True)
    address = attrs.TextAttr('address')
    description = attrs.TextAttr('description')


@register_model_view(IndustrialService, 'list', path='', detail=False)
class IndustrialServiceListView(generic.ObjectListView):
    queryset = IndustrialService.objects.select_related('device', 'virtual_machine', 'interface', 'fieldbus')
    filterset = filtersets.IndustrialServiceFilterSet
    filterset_form = forms.IndustrialServiceFilterForm
    table = tables.IndustrialServiceTable


@register_model_view(IndustrialService)
class IndustrialServiceView(generic.ObjectView):
    queryset = IndustrialService.objects.all()
    template_name = 'generic/object.html'
    layout = layout.SimpleLayout(
        left_panels=[IndustrialServicePanel(), TagsPanel()],
        right_panels=[
            panels.TextCodePanel('evidence', title=_('Evidence')),
            CustomFieldsPanel(),
            panels.CommentsPanel(),
        ],
    )


@register_model_view(IndustrialService, 'add', detail=False)
@register_model_view(IndustrialService, 'edit')
class IndustrialServiceEditView(generic.ObjectEditView):
    queryset = IndustrialService.objects.all()
    form = forms.IndustrialServiceForm


@register_model_view(IndustrialService, 'delete')
class IndustrialServiceDeleteView(generic.ObjectDeleteView):
    queryset = IndustrialService.objects.all()


@register_model_view(IndustrialService, 'bulk_import', path='import', detail=False)
class IndustrialServiceBulkImportView(generic.BulkImportView):
    queryset = IndustrialService.objects.all()
    model_form = forms.IndustrialServiceImportForm


@register_model_view(IndustrialService, 'bulk_edit', path='edit', detail=False)
class IndustrialServiceBulkEditView(generic.BulkEditView):
    queryset = IndustrialService.objects.all()
    filterset = filtersets.IndustrialServiceFilterSet
    table = tables.IndustrialServiceTable
    form = forms.IndustrialServiceBulkEditForm


@register_model_view(IndustrialService, 'bulk_delete', path='delete', detail=False)
class IndustrialServiceBulkDeleteView(generic.BulkDeleteView):
    queryset = IndustrialService.objects.all()
    filterset = filtersets.IndustrialServiceFilterSet
    table = tables.IndustrialServiceTable


#
# Access map
#

def _access_map_context(request, site, max_level):
    conduits = access_map_conduits(
        Conduit.objects.restrict(request.user, 'view'), site=site, max_level=max_level,
    )
    zones = Zone.objects.restrict(request.user, 'view').filter(site=site) if site else Zone.objects.none()
    conduits = list(conduits)
    return {
        'conduits': conduits,
        'svg': access_map_svg(conduits, zones),
        'max_level': max_level,
        'max_level_label': dict(PurdueLevelChoices.CHOICES).get(max_level, max_level),
        'site': site,
    }


class AccessMapView(ContentTypePermissionRequiredMixin, View):
    """Access map for one site (or all sites when none is chosen)."""

    def get_required_permission(self):
        return 'netbox_iec62443.view_conduit'

    def get(self, request):
        max_level = _default_max_level()
        form = forms.AccessMapFilterForm(request.GET or None, initial={'max_level': max_level})
        site = None
        if form.is_valid():
            site = form.cleaned_data.get('site_id')
            max_level = form.cleaned_data.get('max_level') or max_level
        if site is not None and not Site.objects.restrict(request.user, 'view').filter(pk=site.pk).exists():
            site = None
        context = _access_map_context(request, site, max_level)
        return render(request, 'netbox_iec62443/accessmap.html', {
            'form': form,
            'show_site': site is None,
            **context,
        })


@register_model_view(Site, name='iec62443_accessmap', path='access-map')
class SiteAccessMapView(generic.ObjectView):
    queryset = Site.objects.all()
    template_name = 'netbox_iec62443/site_accessmap.html'
    tab = ViewTab(
        label=_('Access map'),
        badge=lambda site: Conduit.objects.filter(
            Q(source_zone__site=site) | Q(destination_zone__site=site)
        ).count(),
        permission='netbox_iec62443.view_conduit',
        weight=2100,
        hide_if_empty=True,
    )

    def get_extra_context(self, request, instance):
        max_level = request.GET.get('max_level') or _default_max_level()
        if max_level not in PurdueLevelChoices.values():
            max_level = _default_max_level()
        return {
            'levels': PurdueLevelChoices.CHOICES,
            **_access_map_context(request, instance, max_level),
        }
