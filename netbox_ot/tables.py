import django_tables2 as tables
from django.utils.translation import gettext_lazy as _

from netbox.tables import PrimaryModelTable, columns
from tenancy.tables import TenancyColumnsMixin

from .models import Conduit, Fieldbus, Flow, FlowHop, IndustrialService, RiskAssessment, Zone

__all__ = (
    'ConduitTable', 'FieldbusTable', 'FlowHopTable', 'FlowTable', 'IndustrialServiceTable', 'RiskAssessmentTable',
    'ZoneTable',
)

ACCESS_BADGES = """
{% for value, label, color in record.get_access_display %}{% badge label bg_color=color %} {% endfor %}
"""
HOPS = """
{% for hop in record.hops.all %}{{ hop.hop|linkify }}{% if not forloop.last %} &rarr; {% endif %}
{% empty %}{{ ''|placeholder }}{% endfor %}
"""
VERDICT = """{% load i18n %}
{% badge record.get_allowed_display bg_color=record.get_allowed_color %}
{% if record.is_expired %}<span class="badge text-bg-danger">{% trans "expired" %}</span>{% endif %}
{% if record.is_review_due %}<span class="badge text-bg-warning">{% trans "review due" %}</span>{% endif %}
"""


class ZoneTable(TenancyColumnsMixin, PrimaryModelTable):
    name = tables.Column(verbose_name=_('Name'), linkify=True)
    site = tables.Column(verbose_name=_('Site'), linkify=True)
    zone_type = columns.ChoiceFieldColumn(verbose_name=_('Type'))
    purdue_level = columns.ChoiceFieldColumn(verbose_name=_('Purdue level'))
    parent = tables.Column(verbose_name=_('Parent'), linkify=True)
    sl_target = tables.Column(verbose_name=_('SL-T'), accessor=tables.A('sl_target_display'), order_by=('sl_target',))
    sl_achieved = tables.Column(verbose_name=_('SL-A'), accessor=tables.A('sl_achieved_display'),
                                order_by=('sl_achieved',))
    accountable = tables.Column(verbose_name=_('Accountable'), linkify=True)
    wireless = columns.BooleanColumn(verbose_name=_('Wireless'))
    temporary_devices = columns.BooleanColumn(verbose_name=_('Temporary devices'))
    device_count = tables.Column(verbose_name=_('Device count'))
    flow_count = tables.Column(verbose_name=_('Flows'))
    conduits = columns.ManyToManyColumn(verbose_name=_('Conduits'), linkify_item=True)
    devices = columns.ManyToManyColumn(verbose_name=_('Devices'), linkify_item=True)
    virtual_machines = columns.ManyToManyColumn(verbose_name=_('Virtual machines'), linkify_item=True)
    prefixes = columns.ManyToManyColumn(verbose_name=_('Prefixes'), linkify_item=True)
    tags = columns.TagColumn(url_name='plugins:netbox_ot:zone_list')

    class Meta(PrimaryModelTable.Meta):
        model = Zone
        fields = (
            'pk', 'id', 'name', 'slug', 'site', 'zone_type', 'purdue_level', 'parent', 'sl_target', 'sl_achieved',
            'accountable', 'wireless', 'temporary_devices', 'device_count', 'flow_count', 'conduits', 'devices',
            'virtual_machines', 'prefixes', 'tenant', 'tenant_group', 'description', 'comments', 'tags', 'created',
            'last_updated',
        )
        default_columns = (
            'pk', 'name', 'site', 'zone_type', 'purdue_level', 'sl_target', 'sl_achieved', 'accountable',
            'device_count', 'flow_count', 'prefixes',
        )


class ConduitTable(PrimaryModelTable):
    name = tables.Column(verbose_name=_('Name'), linkify=True)
    site = tables.Column(verbose_name=_('Site'), linkify=True)
    zones = columns.ManyToManyColumn(verbose_name=_('Zones'), linkify_item=True)
    sl_target = tables.Column(verbose_name=_('SL-T'), accessor=tables.A('sl_target_display'), order_by=('sl_target',))
    sl_achieved = tables.Column(verbose_name=_('SL-A'), accessor=tables.A('sl_achieved_display'),
                                order_by=('sl_achieved',))
    accountable = tables.Column(verbose_name=_('Accountable'), linkify=True)
    enforcing_devices = columns.ManyToManyColumn(verbose_name=_('Enforcing devices'), linkify_item=True)
    enforcing_virtual_machines = columns.ManyToManyColumn(verbose_name=_('Enforcing VMs'), linkify_item=True)
    flow_count = tables.Column(verbose_name=_('Flows'))
    tags = columns.TagColumn(url_name='plugins:netbox_ot:conduit_list')

    class Meta(PrimaryModelTable.Meta):
        model = Conduit
        fields = (
            'pk', 'id', 'name', 'site', 'zones', 'sl_target', 'sl_achieved', 'accountable', 'enforcing_devices',
            'enforcing_virtual_machines', 'flow_count', 'description', 'comments', 'tags', 'created',
            'last_updated',
        )
        default_columns = (
            'pk', 'name', 'site', 'zones', 'sl_target', 'sl_achieved', 'enforcing_devices', 'flow_count',
        )


class FlowTable(PrimaryModelTable):
    name = tables.Column(verbose_name=_('Name'), linkify=True)
    conduit = tables.Column(verbose_name=_('Conduit'), linkify=True)
    source_zone = tables.Column(verbose_name=_('From zone'), linkify=True)
    destination_zone = tables.Column(verbose_name=_('To zone'), linkify=True)
    protocol = columns.ChoiceFieldColumn(verbose_name=_('Protocol'))
    connection = columns.ChoiceFieldColumn(verbose_name=_('Connection'))
    broker_zone = tables.Column(verbose_name=_('Broker zone'), linkify=True)
    topics = columns.ArrayColumn(verbose_name=_('Topics'), orderable=False)
    ports = tables.Column(verbose_name=_('Ports'), accessor=tables.A('ports_display'), orderable=False)
    access = columns.TemplateColumn(verbose_name=_('Access'), template_code=ACCESS_BADGES, orderable=False)
    remote_access = columns.BooleanColumn(verbose_name=_('Remote access'))
    hops = columns.TemplateColumn(verbose_name=_('Through'), template_code=HOPS, orderable=False)
    allowed = columns.TemplateColumn(verbose_name=_('Allowed'), template_code=VERDICT, order_by=('allowed',))
    decided_by = tables.Column(verbose_name=_('Decided by'), linkify=True)
    decided_on = columns.DateColumn(verbose_name=_('Decided on'))
    review_by = columns.DateColumn(verbose_name=_('Review by'))
    expires = columns.DateColumn(verbose_name=_('Expires'))
    first_seen = columns.DateTimeColumn(verbose_name=_('First seen'))
    last_seen = columns.DateTimeColumn(verbose_name=_('Last seen'))
    tags = columns.TagColumn(url_name='plugins:netbox_ot:flow_list')

    class Meta(PrimaryModelTable.Meta):
        model = Flow
        fields = (
            'pk', 'id', 'name', 'conduit', 'source_zone', 'destination_zone', 'connection', 'broker_zone', 'topics',
            'protocol', 'ports', 'access', 'remote_access', 'hops', 'allowed', 'decided_by', 'decided_on', 'review_by',
            'expires', 'first_seen', 'last_seen', 'evidence', 'description', 'comments', 'tags', 'created',
            'last_updated',
        )
        default_columns = (
            'pk', 'name', 'source_zone', 'destination_zone', 'protocol', 'ports', 'access', 'remote_access', 'hops',
            'allowed', 'last_seen',
        )


class FlowHopTable(PrimaryModelTable):
    flow = tables.Column(verbose_name=_('Flow'), linkify=True)
    position = tables.Column(verbose_name=_('Position'), linkify=True)
    hop = tables.Column(verbose_name=_('Runs through'), linkify=True, orderable=False)
    tags = columns.TagColumn(url_name='plugins:netbox_ot:flowhop_list')

    class Meta(PrimaryModelTable.Meta):
        model = FlowHop
        fields = ('pk', 'id', 'flow', 'position', 'hop', 'description', 'comments', 'tags', 'created', 'last_updated')
        default_columns = ('pk', 'flow', 'position', 'hop', 'description')


class FieldbusTable(PrimaryModelTable):
    name = tables.Column(verbose_name=_('Name'), linkify=True)
    site = tables.Column(verbose_name=_('Site'), linkify=True)
    zone = tables.Column(verbose_name=_('Zone'), linkify=True)
    medium = columns.ChoiceFieldColumn(verbose_name=_('Medium'))
    protocol = columns.ChoiceFieldColumn(verbose_name=_('Protocol'))
    gateway = tables.Column(verbose_name=_('Gateway'), linkify=True)
    service_count = tables.Column(verbose_name=_('Services'))
    tags = columns.TagColumn(url_name='plugins:netbox_ot:fieldbus_list')

    class Meta(PrimaryModelTable.Meta):
        model = Fieldbus
        fields = (
            'pk', 'id', 'name', 'site', 'zone', 'medium', 'protocol', 'gateway', 'service_count', 'description',
            'comments', 'tags', 'created', 'last_updated',
        )
        default_columns = (
            'pk', 'name', 'site', 'zone', 'medium', 'protocol', 'gateway', 'service_count',
        )


class IndustrialServiceTable(PrimaryModelTable):
    id = tables.Column(verbose_name=_('ID'), linkify=True)
    parent = tables.Column(verbose_name=_('Device / VM'), linkify=True, order_by=('device__name',
                                                                               'virtual_machine__name'))
    protocol = columns.ChoiceFieldColumn(verbose_name=_('Protocol'), linkify=True)
    role = columns.ChoiceFieldColumn(verbose_name=_('Role'))
    service = tables.Column(verbose_name=_('Application service'), linkify=True)
    ports = tables.Column(verbose_name=_('Ports'), accessor=tables.A('ports_display'), orderable=False)
    fieldbus = tables.Column(verbose_name=_('Fieldbus'), linkify=True)
    tags = columns.TagColumn(url_name='plugins:netbox_ot:industrialservice_list')

    class Meta(PrimaryModelTable.Meta):
        model = IndustrialService
        fields = (
            'pk', 'id', 'parent', 'protocol', 'role', 'service', 'ports', 'fieldbus', 'address', 'evidence',
            'description', 'comments', 'tags', 'created', 'last_updated',
        )
        default_columns = ('pk', 'parent', 'protocol', 'role', 'service', 'ports', 'fieldbus', 'address')


class RiskAssessmentTable(PrimaryModelTable):
    id = tables.Column(verbose_name=_('ID'), linkify=True)
    subject = tables.Column(verbose_name=_('Zone / conduit'), linkify=True, order_by=('zone__name', 'conduit__name'))
    kind = columns.ChoiceFieldColumn(verbose_name=_('Kind'))
    status = columns.ChoiceFieldColumn(verbose_name=_('Status'))
    assessed_on = columns.DateColumn(verbose_name=_('Assessed on'), linkify=True)
    assessed_by = tables.Column(verbose_name=_('Assessed by'), linkify=True)
    approved_by = tables.Column(verbose_name=_('Approved by'), linkify=True)
    approved_on = columns.DateColumn(verbose_name=_('Approved on'))
    next_review = columns.DateColumn(verbose_name=_('Next review'))
    unmitigated_risk = columns.ChoiceFieldColumn(verbose_name=_('Unmitigated'))
    residual_risk = columns.ChoiceFieldColumn(verbose_name=_('Residual'))
    tolerable_risk = columns.ChoiceFieldColumn(verbose_name=_('Tolerable'))
    tags = columns.TagColumn(url_name='plugins:netbox_ot:riskassessment_list')

    class Meta(PrimaryModelTable.Meta):
        model = RiskAssessment
        fields = (
            'pk', 'id', 'subject', 'kind', 'status', 'assessed_on', 'assessed_by', 'approved_by', 'approved_on',
            'next_review', 'method', 'unmitigated_risk', 'residual_risk', 'tolerable_risk', 'document', 'description',
            'comments', 'tags', 'created', 'last_updated',
        )
        default_columns = (
            'pk', 'subject', 'kind', 'status', 'assessed_on', 'approved_by', 'unmitigated_risk', 'residual_risk',
            'tolerable_risk', 'next_review',
        )
