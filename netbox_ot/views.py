from django.contrib import messages
from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.generic import View

from dcim.models import Site
from extras.ui.panels import CustomFieldsPanel, TagsPanel
from netbox.ui import actions, attrs, layout, panels
from netbox.views import generic
from utilities.views import ContentTypePermissionRequiredMixin, ViewTab, register_model_view

from . import filtersets, forms, sl, tables
from .accessmap import access_map_diagram, access_map_flows, accessmap_labels, attention
from .branching import branch_names, branching_installed
from .checks import CHECKS, run_checks, summary
from .choices import ConnectionChoices
from .customfields import get_sl_capability
from .models import (
    Conduit,
    Fieldbus,
    Flow,
    FlowHop,
    IndustrialService,
    PluginSettings,
    RequirementStatus,
    RiskAssessment,
    SystemRequirement,
    Zone,
)
from .register import build_register, register_csv
from .rules import build_rules, rules_csv


def _default_max_level():
    from django.conf import settings
    return str(settings.PLUGINS_CONFIG.get('netbox_ot', {}).get('access_map_max_level', '2'))


def _ids_or_none(queryset):
    # An empty id list would mean "no filter" (all objects); [0] matches nothing.
    return list(queryset.values_list('pk', flat=True)) or [0]


#
# Panels
#

class ZonePanel(panels.ObjectAttributesPanel):
    name = attrs.TextAttr('name')
    site = attrs.RelatedObjectAttr('site', linkify=True)
    zone_type = attrs.ChoiceAttr('zone_type', label=_('Zone type'))
    purdue_level = attrs.ChoiceAttr('purdue_level', label=_('Purdue level'))
    parent = attrs.RelatedObjectAttr('parent', linkify=True, label=_('Parent zone'))
    accountable = attrs.RelatedObjectAttr('accountable', linkify=True, label=_('Accountable'))
    wireless = attrs.BooleanAttr('wireless', label=_('Wireless'))
    temporary_devices = attrs.BooleanAttr('temporary_devices', label=_('Temporarily connected devices'))
    tenant = attrs.RelatedObjectAttr('tenant', linkify=True, grouped_by='group')
    description = attrs.TextAttr('description')


class ConduitPanel(panels.ObjectAttributesPanel):
    name = attrs.TextAttr('name')
    site = attrs.RelatedObjectAttr('site', linkify=True)
    accountable = attrs.RelatedObjectAttr('accountable', linkify=True, label=_('Accountable'))
    description = attrs.TextAttr('description')


class SecurityLevelPanel(panels.Panel):
    """SL-T and SL-A per foundational requirement; for a zone also the lowest SL-C among its member devices."""
    template_name = 'netbox_ot/inc/sl_panel.html'
    title = _('Security levels')

    def get_context(self, context):
        obj = context['object']
        capability = None
        if isinstance(obj, Zone):
            capability = sl.minimum(get_sl_capability(d) for d in obj.devices.select_related('device_type'))
        rows = [(*row, capability[i] if capability else None)
                for i, row in enumerate(sl.rows(obj.sl_target, obj.sl_achieved))]
        return {**super().get_context(context), 'rows': rows, 'capability': capability}


class RiskAssessmentPanel(panels.ObjectAttributesPanel):
    zone = attrs.RelatedObjectAttr('zone', linkify=True)
    conduit = attrs.RelatedObjectAttr('conduit', linkify=True)
    kind = attrs.ChoiceAttr('kind')
    status = attrs.ChoiceAttr('status')
    assessed_on = attrs.DateTimeAttr('assessed_on', spec='date', label=_('Assessed on'))
    assessed_by = attrs.RelatedObjectAttr('assessed_by', linkify=True, label=_('Assessed by'))
    approved_on = attrs.DateTimeAttr('approved_on', spec='date', label=_('Approved on'))
    approved_by = attrs.RelatedObjectAttr('approved_by', linkify=True, label=_('Approved by'))
    next_review = attrs.DateTimeAttr('next_review', spec='date', label=_('Next review'))
    method = attrs.TextAttr('method')
    document = attrs.TextAttr('document')
    description = attrs.TextAttr('description')


class RiskLevelsPanel(panels.ObjectAttributesPanel):
    unmitigated_risk = attrs.ChoiceAttr('unmitigated_risk', label=_('Unmitigated risk'))
    residual_risk = attrs.ChoiceAttr('residual_risk', label=_('Residual risk'))
    tolerable_risk = attrs.ChoiceAttr('tolerable_risk', label=_('Tolerable risk'))
    residual_above_tolerable = attrs.BooleanAttr('residual_above_tolerable', label=_('Residual above tolerable'))


def _requirement_statuses_panel(field):
    return panels.ObjectsTablePanel(
        'netbox_ot.requirementstatus',
        filters={f'{field}_id': lambda ctx: ctx['object'].pk},
        exclude_columns=['subject'],
        title=_('System requirements (IEC 62443-3-3)'),
        actions=[actions.AddObject('netbox_ot.requirementstatus', label=_('Add'),
                                   url_params={field: lambda ctx: ctx['object'].pk})],
    )


def _risk_assessments_panel(field):
    return panels.ObjectsTablePanel(
        'netbox_ot.riskassessment',
        filters={f'{field}_id': lambda ctx: ctx['object'].pk},
        exclude_columns=['subject'],
        title=_('Risk assessments'),
        actions=[actions.AddObject('netbox_ot.riskassessment', label=_('Add'),
                                   url_params={field: lambda ctx: ctx['object'].pk})],
    )


class FlowPanel(panels.ObjectAttributesPanel):
    name = attrs.TextAttr('name')
    source_zone = attrs.RelatedObjectAttr('source_zone', linkify=True, label=_('From zone'))
    destination_zone = attrs.RelatedObjectAttr('destination_zone', linkify=True, label=_('To zone'))
    conduit = attrs.RelatedObjectAttr('conduit', linkify=True)
    connection = attrs.TemplatedAttr(
        'connection', label=_('Connection'), template_name='netbox_ot/inc/connection_attr.html',
    )
    broker_zone = attrs.RelatedObjectAttr('broker_zone', linkify=True, label=_('Broker zone'))
    topics = attrs.ArrayAttr('topics', label=_('Topics'))
    protocol = attrs.ChoiceAttr('protocol')
    ports = attrs.TextAttr('ports_display', label=_('Ports'))
    access = attrs.TemplatedAttr('access', label=_('Access'), template_name='netbox_ot/inc/access_attr.html')
    remote_access = attrs.BooleanAttr('remote_access', label=_('Remote access'))
    description = attrs.TextAttr('description')


class FlowVerdictPanel(panels.ObjectAttributesPanel):
    allowed = attrs.TemplatedAttr('allowed', label=_('Allowed'), template_name='netbox_ot/inc/verdict_attr.html')
    decided_by = attrs.RelatedObjectAttr('decided_by', linkify=True, label=_('Decided by'))
    decided_on = attrs.DateTimeAttr('decided_on', spec='date', label=_('Decided on'))
    review_by = attrs.DateTimeAttr('review_by', spec='date', label=_('Review by'))
    expires = attrs.DateTimeAttr('expires', spec='date', label=_('Expires'))


class FlowSeenPanel(panels.ObjectAttributesPanel):
    first_seen = attrs.DateTimeAttr('first_seen', label=_('First seen'))
    last_seen = attrs.DateTimeAttr('last_seen', label=_('Last seen'))


class FlowHopPanel(panels.ObjectAttributesPanel):
    flow = attrs.RelatedObjectAttr('flow', linkify=True)
    position = attrs.TextAttr('position')
    hop = attrs.RelatedObjectAttr('hop', linkify=True, label=_('Runs through'))
    description = attrs.TextAttr('description')


#
# Zones
#

@register_model_view(Zone, 'list', path='', detail=False)
class ZoneListView(generic.ObjectListView):
    queryset = Zone.objects.annotate(
        device_count=Count('devices', distinct=True),
        flow_count=Count('flows_out', distinct=True) + Count('flows_in', distinct=True),
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
            SecurityLevelPanel(),
            CustomFieldsPanel(),
            panels.CommentsPanel(),
        ],
        bottom_panels=[
            _risk_assessments_panel('zone'),
            _requirement_statuses_panel('zone'),
            panels.ObjectsTablePanel(
                'netbox_ot.zone',
                filters={'parent_id': lambda ctx: ctx['object'].pk},
                title=_('Sub-zones'),
            ),
            panels.ObjectsTablePanel(
                'netbox_ot.conduit',
                filters={'zone_id': lambda ctx: ctx['object'].pk},
                title=_('Conduits'),
            ),
            panels.ObjectsTablePanel(
                'netbox_ot.flow',
                filters={'zone_id': lambda ctx: ctx['object'].pk},
                title=_('Flows'),
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
    queryset = Conduit.objects.annotate(flow_count=Count('flows', distinct=True))
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
            TagsPanel(),
        ],
        right_panels=[
            SecurityLevelPanel(),
            CustomFieldsPanel(),
            panels.CommentsPanel(),
        ],
        bottom_panels=[
            panels.ObjectsTablePanel(
                'netbox_ot.zone',
                filters={'conduit_id': lambda ctx: ctx['object'].pk},
                title=_('Zones'),
            ),
            _risk_assessments_panel('conduit'),
            _requirement_statuses_panel('conduit'),
            panels.ObjectsTablePanel(
                'dcim.device',
                filters={'id': lambda ctx: _ids_or_none(ctx['object'].enforcing_devices.all())},
                title=_('Enforced by (devices)'),
            ),
            panels.ObjectsTablePanel(
                'virtualization.virtualmachine',
                filters={'id': lambda ctx: _ids_or_none(ctx['object'].enforcing_virtual_machines.all())},
                title=_('Enforced by (virtual machines)'),
            ),
            panels.ObjectsTablePanel(
                'netbox_ot.flow',
                filters={'conduit_id': lambda ctx: ctx['object'].pk},
                title=_('Flows'),
            ),
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
# Flows
#

@register_model_view(Flow, 'list', path='', detail=False)
class FlowListView(generic.ObjectListView):
    queryset = Flow.objects.select_related('source_zone', 'destination_zone', 'conduit', 'decided_by').prefetch_related(
        'hops__device', 'hops__virtual_machine', 'hops__tunnel',
    )
    filterset = filtersets.FlowFilterSet
    filterset_form = forms.FlowFilterForm
    table = tables.FlowTable


@register_model_view(Flow)
class FlowView(generic.ObjectView):
    queryset = Flow.objects.all()
    template_name = 'generic/object.html'
    layout = layout.SimpleLayout(
        left_panels=[
            FlowPanel(),
            FlowVerdictPanel(title=_('Verdict')),
            TagsPanel(),
        ],
        right_panels=[
            FlowSeenPanel(title=_('Observed')),
            panels.TextCodePanel('evidence', title=_('Evidence')),
            CustomFieldsPanel(),
            panels.CommentsPanel(),
        ],
        bottom_panels=[
            panels.ObjectsTablePanel(
                'netbox_ot.flowhop',
                filters={'flow_id': lambda ctx: ctx['object'].pk},
                exclude_columns=['flow'],
                title=_('Path (hops in order)'),
                actions=[
                    actions.AddObject(
                        'netbox_ot.flowhop', label=_('Add hop'),
                        url_params={'flow': lambda ctx: ctx['object'].pk},
                    ),
                ],
            ),
        ],
    )


@register_model_view(Flow, 'add', detail=False)
@register_model_view(Flow, 'edit')
class FlowEditView(generic.ObjectEditView):
    queryset = Flow.objects.all()
    form = forms.FlowForm


@register_model_view(Flow, 'delete')
class FlowDeleteView(generic.ObjectDeleteView):
    queryset = Flow.objects.all()


@register_model_view(Flow, 'bulk_import', path='import', detail=False)
class FlowBulkImportView(generic.BulkImportView):
    queryset = Flow.objects.all()
    model_form = forms.FlowImportForm


@register_model_view(Flow, 'bulk_edit', path='edit', detail=False)
class FlowBulkEditView(generic.BulkEditView):
    queryset = Flow.objects.all()
    filterset = filtersets.FlowFilterSet
    table = tables.FlowTable
    form = forms.FlowBulkEditForm


@register_model_view(Flow, 'bulk_delete', path='delete', detail=False)
class FlowBulkDeleteView(generic.BulkDeleteView):
    queryset = Flow.objects.all()
    filterset = filtersets.FlowFilterSet
    table = tables.FlowTable


#
# Flow hops
#

@register_model_view(FlowHop, 'list', path='', detail=False)
class FlowHopListView(generic.ObjectListView):
    queryset = FlowHop.objects.select_related('flow', 'device', 'virtual_machine', 'tunnel')
    filterset = filtersets.FlowHopFilterSet
    filterset_form = forms.FlowHopFilterForm
    table = tables.FlowHopTable


@register_model_view(FlowHop)
class FlowHopView(generic.ObjectView):
    queryset = FlowHop.objects.all()
    template_name = 'generic/object.html'
    layout = layout.SimpleLayout(
        left_panels=[FlowHopPanel(), TagsPanel()],
        right_panels=[CustomFieldsPanel(), panels.CommentsPanel()],
    )


@register_model_view(FlowHop, 'add', detail=False)
@register_model_view(FlowHop, 'edit')
class FlowHopEditView(generic.ObjectEditView):
    queryset = FlowHop.objects.all()
    form = forms.FlowHopForm


@register_model_view(FlowHop, 'delete')
class FlowHopDeleteView(generic.ObjectDeleteView):
    queryset = FlowHop.objects.all()


@register_model_view(FlowHop, 'bulk_import', path='import', detail=False)
class FlowHopBulkImportView(generic.BulkImportView):
    queryset = FlowHop.objects.all()
    model_form = forms.FlowHopImportForm


@register_model_view(FlowHop, 'bulk_edit', path='edit', detail=False)
class FlowHopBulkEditView(generic.BulkEditView):
    queryset = FlowHop.objects.all()
    filterset = filtersets.FlowHopFilterSet
    table = tables.FlowHopTable
    form = forms.FlowHopBulkEditForm


@register_model_view(FlowHop, 'bulk_delete', path='delete', detail=False)
class FlowHopBulkDeleteView(generic.BulkDeleteView):
    queryset = FlowHop.objects.all()
    filterset = filtersets.FlowHopFilterSet
    table = tables.FlowHopTable


#
# Risk assessments
#

@register_model_view(RiskAssessment, 'list', path='', detail=False)
class RiskAssessmentListView(generic.ObjectListView):
    queryset = RiskAssessment.objects.select_related('zone', 'conduit', 'assessed_by', 'approved_by')
    filterset = filtersets.RiskAssessmentFilterSet
    filterset_form = forms.RiskAssessmentFilterForm
    table = tables.RiskAssessmentTable


@register_model_view(RiskAssessment)
class RiskAssessmentView(generic.ObjectView):
    queryset = RiskAssessment.objects.all()
    template_name = 'generic/object.html'
    layout = layout.SimpleLayout(
        left_panels=[
            RiskAssessmentPanel(),
            RiskLevelsPanel(title=_('Risk')),
            TagsPanel(),
        ],
        right_panels=[
            panels.TextCodePanel('threats', title=_('Threats')),
            panels.TextCodePanel('vulnerabilities', title=_('Vulnerabilities')),
            panels.TextCodePanel('consequences', title=_('Consequences')),
            panels.TextCodePanel('countermeasures', title=_('Countermeasures')),
            CustomFieldsPanel(),
            panels.CommentsPanel(),
        ],
    )


@register_model_view(RiskAssessment, 'add', detail=False)
@register_model_view(RiskAssessment, 'edit')
class RiskAssessmentEditView(generic.ObjectEditView):
    queryset = RiskAssessment.objects.all()
    form = forms.RiskAssessmentForm


@register_model_view(RiskAssessment, 'delete')
class RiskAssessmentDeleteView(generic.ObjectDeleteView):
    queryset = RiskAssessment.objects.all()


@register_model_view(RiskAssessment, 'bulk_import', path='import', detail=False)
class RiskAssessmentBulkImportView(generic.BulkImportView):
    queryset = RiskAssessment.objects.all()
    model_form = forms.RiskAssessmentImportForm


@register_model_view(RiskAssessment, 'bulk_edit', path='edit', detail=False)
class RiskAssessmentBulkEditView(generic.BulkEditView):
    queryset = RiskAssessment.objects.all()
    filterset = filtersets.RiskAssessmentFilterSet
    table = tables.RiskAssessmentTable
    form = forms.RiskAssessmentBulkEditForm


@register_model_view(RiskAssessment, 'bulk_delete', path='delete', detail=False)
class RiskAssessmentBulkDeleteView(generic.BulkDeleteView):
    queryset = RiskAssessment.objects.all()
    filterset = filtersets.RiskAssessmentFilterSet
    table = tables.RiskAssessmentTable


#
# System requirements and their status per zone or conduit
#

class SystemRequirementPanel(panels.ObjectAttributesPanel):
    identifier = attrs.TextAttr('identifier')
    edition = attrs.ChoiceAttr('edition')
    foundational_requirement = attrs.ChoiceAttr('foundational_requirement', label=_('Foundational requirement'))
    parent = attrs.RelatedObjectAttr('parent', linkify=True, label=_('Requirement'))
    security_level = attrs.TextAttr('security_level', label=_('Applies from SL'))
    description = attrs.TextAttr('description')


class RequirementStatusPanel(panels.ObjectAttributesPanel):
    zone = attrs.RelatedObjectAttr('zone', linkify=True)
    conduit = attrs.RelatedObjectAttr('conduit', linkify=True)
    requirement = attrs.RelatedObjectAttr('requirement', linkify=True)
    status = attrs.ChoiceAttr('status')
    risk_assessment = attrs.RelatedObjectAttr('risk_assessment', linkify=True, label=_('Risk assessment'))
    assessed_by = attrs.RelatedObjectAttr('assessed_by', linkify=True, label=_('Assessed by'))
    assessed_on = attrs.DateTimeAttr('assessed_on', spec='date', label=_('Assessed on'))
    description = attrs.TextAttr('description')


@register_model_view(SystemRequirement, 'list', path='', detail=False)
class SystemRequirementListView(generic.ObjectListView):
    queryset = SystemRequirement.objects.select_related('parent').annotate(status_count=Count('statuses'))
    filterset = filtersets.SystemRequirementFilterSet
    filterset_form = forms.SystemRequirementFilterForm
    table = tables.SystemRequirementTable


@register_model_view(SystemRequirement)
class SystemRequirementView(generic.ObjectView):
    queryset = SystemRequirement.objects.all()
    template_name = 'generic/object.html'
    layout = layout.SimpleLayout(
        left_panels=[
            SystemRequirementPanel(),
            TagsPanel(),
        ],
        right_panels=[
            panels.TextCodePanel('wording', title=_('Wording (from your copy of the standard)')),
            CustomFieldsPanel(),
            panels.CommentsPanel(),
        ],
        bottom_panels=[
            panels.ObjectsTablePanel(
                'netbox_ot.systemrequirement',
                filters={'parent_id': lambda ctx: ctx['object'].pk},
                title=_('Requirement enhancements'),
            ),
            panels.ObjectsTablePanel(
                'netbox_ot.requirementstatus',
                filters={'requirement_id': lambda ctx: ctx['object'].pk},
                exclude_columns=['requirement'],
                title=_('Status per zone and conduit'),
            ),
        ],
    )


@register_model_view(SystemRequirement, 'add', detail=False)
@register_model_view(SystemRequirement, 'edit')
class SystemRequirementEditView(generic.ObjectEditView):
    queryset = SystemRequirement.objects.all()
    form = forms.SystemRequirementForm


@register_model_view(SystemRequirement, 'delete')
class SystemRequirementDeleteView(generic.ObjectDeleteView):
    queryset = SystemRequirement.objects.all()


@register_model_view(SystemRequirement, 'bulk_import', path='import', detail=False)
class SystemRequirementBulkImportView(generic.BulkImportView):
    queryset = SystemRequirement.objects.all()
    model_form = forms.SystemRequirementImportForm


@register_model_view(SystemRequirement, 'bulk_edit', path='edit', detail=False)
class SystemRequirementBulkEditView(generic.BulkEditView):
    queryset = SystemRequirement.objects.annotate(status_count=Count('statuses'))
    filterset = filtersets.SystemRequirementFilterSet
    table = tables.SystemRequirementTable
    form = forms.SystemRequirementBulkEditForm


@register_model_view(SystemRequirement, 'bulk_delete', path='delete', detail=False)
class SystemRequirementBulkDeleteView(generic.BulkDeleteView):
    queryset = SystemRequirement.objects.annotate(status_count=Count('statuses'))
    filterset = filtersets.SystemRequirementFilterSet
    table = tables.SystemRequirementTable


@register_model_view(RequirementStatus, 'list', path='', detail=False)
class RequirementStatusListView(generic.ObjectListView):
    queryset = RequirementStatus.objects.select_related(
        'zone', 'conduit', 'requirement', 'risk_assessment', 'assessed_by',
    )
    filterset = filtersets.RequirementStatusFilterSet
    filterset_form = forms.RequirementStatusFilterForm
    table = tables.RequirementStatusTable


@register_model_view(RequirementStatus)
class RequirementStatusView(generic.ObjectView):
    queryset = RequirementStatus.objects.all()
    template_name = 'generic/object.html'
    layout = layout.SimpleLayout(
        left_panels=[
            RequirementStatusPanel(),
            TagsPanel(),
        ],
        right_panels=[
            panels.TextCodePanel('countermeasure', title=_('Compensating countermeasure')),
            panels.TextCodePanel('evidence', title=_('Evidence')),
            CustomFieldsPanel(),
            panels.CommentsPanel(),
        ],
    )


@register_model_view(RequirementStatus, 'add', detail=False)
@register_model_view(RequirementStatus, 'edit')
class RequirementStatusEditView(generic.ObjectEditView):
    queryset = RequirementStatus.objects.all()
    form = forms.RequirementStatusForm


@register_model_view(RequirementStatus, 'delete')
class RequirementStatusDeleteView(generic.ObjectDeleteView):
    queryset = RequirementStatus.objects.all()


@register_model_view(RequirementStatus, 'bulk_import', path='import', detail=False)
class RequirementStatusBulkImportView(generic.BulkImportView):
    queryset = RequirementStatus.objects.all()
    model_form = forms.RequirementStatusImportForm


@register_model_view(RequirementStatus, 'bulk_edit', path='edit', detail=False)
class RequirementStatusBulkEditView(generic.BulkEditView):
    queryset = RequirementStatus.objects.all()
    filterset = filtersets.RequirementStatusFilterSet
    table = tables.RequirementStatusTable
    form = forms.RequirementStatusBulkEditForm


@register_model_view(RequirementStatus, 'bulk_delete', path='delete', detail=False)
class RequirementStatusBulkDeleteView(generic.BulkDeleteView):
    queryset = RequirementStatus.objects.all()
    filterset = filtersets.RequirementStatusFilterSet
    table = tables.RequirementStatusTable


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
                'netbox_ot.industrialservice',
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
    service = attrs.RelatedObjectAttr('service', linkify=True, label=_('Application service'))
    ports = attrs.TextAttr('ports_display', label=_('Ports'))
    fieldbus = attrs.RelatedObjectAttr('fieldbus', linkify=True)
    address = attrs.TextAttr('address')
    description = attrs.TextAttr('description')


@register_model_view(IndustrialService, 'list', path='', detail=False)
class IndustrialServiceListView(generic.ObjectListView):
    queryset = IndustrialService.objects.select_related('device', 'virtual_machine', 'service', 'fieldbus')
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

def _access_map_context(request, site, form):
    """The access map of a site (or of all sites, without the diagram) as the bound filter form asks for it."""
    visible = Flow.objects.restrict(request.user, 'view')
    zone_queryset = Zone.objects.restrict(request.user, 'view')
    chosen = form.cleaned_data if form.is_valid() else {}
    max_level = chosen.get('max_level') or _default_max_level()
    collapse = bool(chosen.get('collapse'))
    zones = list(chosen.get('zone_id') or ())
    if zones and collapse:
        # A box of the collapsed diagram stands for a zone and everything below it
        below = zones
        while below:
            below = list(zone_queryset.filter(parent__in=below).exclude(pk__in=[z.pk for z in zones]))
            zones += below
    filters = {
        'verdict': chosen.get('verdict') or (),
        'protocol': chosen.get('protocol') or (),
        'connection': chosen.get('connection') or (),
        'zones': zones,
        'remote_access': chosen.get('remote_access'),
    }
    filtered = any(v not in ((), [], None) for v in filters.values())
    flows = list(access_map_flows(visible, site=site, max_level=max_level, **filters))
    site_flows = visible.filter(Q(source_zone__site=site) | Q(destination_zone__site=site)) if site else visible
    context = {
        'form': form,
        'flows': flows,
        'flows_total': access_map_flows(visible, site=site, max_level=max_level).count() if filtered else len(flows),
        'filtered': filtered,
        'attention': attention(site_flows),
        'max_level': max_level,
        'site': site,
    }
    if site is not None:
        # One diagram per site: the zones of several sites in one picture say nothing
        site_zones = zone_queryset.filter(site=site)
        drawn = {pk for f in flows for pk in (f.source_zone_id, f.destination_zone_id)}
        context['diagram'] = access_map_diagram(
            flows, site_zones if chosen.get('empty') else (), collapse=collapse, zone_queryset=zone_queryset,
        )
        context['diagram']['data']['labels'] = accessmap_labels()
        context['zones_not_drawn'] = 0 if chosen.get('empty') else site_zones.exclude(pk__in=drawn).count()
    return context


class AccessMapView(ContentTypePermissionRequiredMixin, View):
    """Access map for one site (or all sites when none is chosen)."""

    def get_required_permission(self):
        return 'netbox_ot.view_flow'

    def get(self, request):
        form = forms.AccessMapFilterForm(request.GET or None, initial={'max_level': _default_max_level()})
        site = form.cleaned_data.get('site_id') if form.is_valid() else None
        if site is not None and not Site.objects.restrict(request.user, 'view').filter(pk=site.pk).exists():
            site = None
        return render(request, 'netbox_ot/accessmap.html', {
            'show_site': site is None,
            **_access_map_context(request, site, form),
        })


@register_model_view(Site, name='ot_accessmap', path='access-map')
class SiteAccessMapView(generic.ObjectView):
    queryset = Site.objects.all()
    template_name = 'netbox_ot/site_accessmap.html'
    tab = ViewTab(
        label=_('Access map'),
        badge=lambda site: Flow.objects.filter(
            Q(source_zone__site=site) | Q(destination_zone__site=site)
        ).count(),
        permission='netbox_ot.view_flow',
        weight=2100,
        hide_if_empty=True,
    )

    def get_extra_context(self, request, instance):
        form = forms.AccessMapFilterForm(request.GET or None, initial={'max_level': _default_max_level()},
                                         site=instance)
        return _access_map_context(request, instance, form)


#
# Consistency checks and the register
#

class ChecksView(ContentTypePermissionRequiredMixin, View):
    """Consistency checks for one site (or all sites)."""

    def get_required_permission(self):
        return 'netbox_ot.view_zone'

    def get(self, request):
        form = forms.ChecksFilterForm(request.GET or None)
        site, severities = None, None
        if form.is_valid():
            site = form.cleaned_data.get('site_id')
            severities = form.cleaned_data.get('severity') or None
        if site is not None and not Site.objects.restrict(request.user, 'view').filter(pk=site.pk).exists():
            site = None
        findings = run_checks(site=site, user=request.user, severities=severities)
        return render(request, 'netbox_ot/checks.html', {
            'form': form,
            'site': site,
            'findings': findings,
            'summary': summary(findings),
            'checks': CHECKS,
        })


def _register_badge(site):
    return Zone.objects.filter(site=site).count()


@register_model_view(Site, name='ot_register', path='ot-register')
class SiteRegisterView(generic.ObjectView):
    """The zone and conduit register of a site: the audit deliverable, with CSV export."""
    queryset = Site.objects.all()
    template_name = 'netbox_ot/site_register.html'
    tab = ViewTab(
        label=_('Zone register'),
        badge=_register_badge,
        permission='netbox_ot.view_zone',
        weight=2110,
        hide_if_empty=True,
    )

    def get(self, request, **kwargs):
        table = request.GET.get('export')
        if table == 'rules':
            site = self.get_object(**kwargs)
            flows = Flow.objects.restrict(request.user, 'view').filter(
                Q(source_zone__site=site) | Q(destination_zone__site=site))
            rules, _skipped = build_rules(flows, include_denied=request.GET.get('include_denied') == 'true')
            response = HttpResponse(rules_csv(rules), content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = f'attachment; filename="{site.slug}-ot-firewall-rules.csv"'
            return response
        if table in ('zones', 'conduits', 'flows', 'requirements'):
            site = self.get_object(**kwargs)
            data = register_csv(build_register(site, user=request.user), table)
            response = HttpResponse(data, content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = f'attachment; filename="{site.slug}-ot-{table}.csv"'
            return response
        return super().get(request, **kwargs)

    def get_extra_context(self, request, instance):
        return {
            'register': build_register(instance, user=request.user),
            # The register holds display labels; the page leaves out the default one
            'default_connection': ConnectionChoices.label(ConnectionChoices.CLIENT_SERVER),
        }


#
# Settings
#

class PluginSettingsView(ContentTypePermissionRequiredMixin, View):
    """
    The plugin settings an administrator changes in the GUI. Today these are only the branching settings, so
    the page exists only with netbox-branching installed.
    """

    def get_required_permission(self):
        return 'netbox_ot.change_pluginsettings'

    def dispatch(self, request, *args, **kwargs):
        if not branching_installed():
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def _render(self, request, form):
        return render(request, 'netbox_ot/settings.html', {
            'form': form,
            'settings': form.instance,
            'branches': branch_names(),
        })

    def get(self, request):
        return self._render(request, forms.PluginSettingsForm(instance=PluginSettings.load()))

    def post(self, request):
        form = forms.PluginSettingsForm(request.POST, instance=PluginSettings.load())
        if not form.is_valid():
            return self._render(request, form)
        form.instance.updated_by = request.user.username
        form.save()
        messages.success(request, _('Settings saved'))
        return redirect('plugins:netbox_ot:settings')
