from django import forms
from django.contrib.postgres.forms import SimpleArrayField
from django.utils.translation import gettext_lazy as _

from dcim.models import Device, Site
from ipam.forms.bulk_import import ServicePortMappingsImportMixin
from ipam.forms.fields import PortMappingField
from ipam.models import Prefix, Service
from netbox.forms import (
    PrimaryModelBulkEditForm,
    PrimaryModelFilterSetForm,
    PrimaryModelForm,
    PrimaryModelImportForm,
)
from tenancy.forms import TenancyFilterForm, TenancyForm
from tenancy.models import Contact, Tenant
from utilities.forms import add_blank_choice
from utilities.forms.constants import BOOLEAN_WITH_BLANK_CHOICES
from utilities.forms.fields import (
    CSVChoiceField,
    CSVModelChoiceField,
    CSVModelMultipleChoiceField,
    CSVMultipleChoiceField,
    DynamicModelChoiceField,
    DynamicModelMultipleChoiceField,
    SlugField,
    TagFilterField,
)
from utilities.forms.rendering import FieldSet
from utilities.forms.widgets import DatePicker, DateTimePicker
from virtualization.models import VirtualMachine
from vpn.models import Tunnel

from . import sl
from .choices import (
    AccessChoices,
    FieldbusMediumChoices,
    FlowAllowedChoices,
    FlowProtocolChoices,
    IndustrialProtocolChoices,
    PurdueLevelChoices,
    RiskAssessmentKindChoices,
    RiskAssessmentStatusChoices,
    RiskLevelChoices,
    ServiceRoleChoices,
    ZoneTypeChoices,
)
from .models import Conduit, Fieldbus, Flow, FlowHop, IndustrialService, PluginSettings, RiskAssessment, Zone

__all__ = (
    'AccessMapFilterForm',
    'ChecksFilterForm',
    'ConduitBulkEditForm',
    'ConduitFilterForm',
    'ConduitForm',
    'ConduitImportForm',
    'FieldbusBulkEditForm',
    'FieldbusFilterForm',
    'FieldbusForm',
    'FieldbusImportForm',
    'FlowBulkEditForm',
    'FlowFilterForm',
    'FlowForm',
    'FlowHopBulkEditForm',
    'FlowHopFilterForm',
    'FlowHopForm',
    'FlowHopImportForm',
    'FlowImportForm',
    'IndustrialServiceBulkEditForm',
    'IndustrialServiceFilterForm',
    'IndustrialServiceForm',
    'IndustrialServiceImportForm',
    'PluginSettingsForm',
    'RiskAssessmentBulkEditForm',
    'RiskAssessmentFilterForm',
    'RiskAssessmentForm',
    'RiskAssessmentImportForm',
    'ZoneBulkEditForm',
    'ZoneFilterForm',
    'ZoneForm',
    'ZoneImportForm',
)


class SLVectorField(forms.CharField):
    """A security level vector: one level for every FR ("2") or seven, one per FR ("2,2,2,1,2,1,1")."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('required', False)
        kwargs.setdefault('help_text', _('One level for every FR (e.g. "2"), or seven in FR order IAC, UC, SI, DC, '
                                         'RDF, TRE, RA (e.g. "2,2,2,1,2,1,1")'))
        super().__init__(*args, **kwargs)

    def prepare_value(self, value):
        if isinstance(value, (list, tuple)):
            return ','.join(str(x) for x in value)
        return value

    def to_python(self, value):
        value = super().to_python(value)
        return sl.parse(value) if value else None



def _scope_zones_to_site(form, data, fields):
    """Zone names are unique per site: look CSV zone names up within the row's site (or among zones without one)."""
    params = {'site__name': data.get('site')} if data.get('site') else {'site__isnull': True}
    for field in fields:
        form.fields[field].queryset = form.fields[field].queryset.filter(**params)


#
# Zones
#

class ZoneForm(TenancyForm, PrimaryModelForm):
    slug = SlugField()
    site = DynamicModelChoiceField(label=_('Site'), queryset=Site.objects.all(), required=False)
    purdue_level = forms.ChoiceField(
        label=_('Purdue level'), choices=add_blank_choice(PurdueLevelChoices), required=False,
        help_text=Zone._meta.get_field('purdue_level').help_text,
    )
    sl_target = SLVectorField(label=_('SL-T'))
    sl_achieved = SLVectorField(label=_('SL-A'))
    accountable = DynamicModelChoiceField(label=_('Accountable'), queryset=Contact.objects.all(), required=False)
    parent = DynamicModelChoiceField(
        label=_('Parent zone'), queryset=Zone.objects.all(), required=False, query_params={'site_id': '$site'},
    )
    devices = DynamicModelMultipleChoiceField(
        label=_('Devices'), queryset=Device.objects.all(), required=False,
        query_params={'site_id': '$site'},
    )
    virtual_machines = DynamicModelMultipleChoiceField(
        label=_('Virtual machines'), queryset=VirtualMachine.objects.all(), required=False,
        query_params={'site_id': '$site'},
    )
    prefixes = DynamicModelMultipleChoiceField(
        label=_('Prefixes'), queryset=Prefix.objects.all(), required=False,
    )

    fieldsets = (
        FieldSet('name', 'slug', 'site', 'zone_type', 'purdue_level', 'parent', 'description', 'tags',
                 name=_('Zone')),
        FieldSet('sl_target', 'sl_achieved', 'accountable', name=_('Security')),
        FieldSet('wireless', 'temporary_devices', name=_('Attributes (IEC 62443-3-2)')),
        FieldSet('devices', 'virtual_machines', 'prefixes', name=_('Members')),
        FieldSet('tenant_group', 'tenant', name=_('Tenancy')),
    )

    class Meta:
        model = Zone
        fields = (
            'name', 'slug', 'site', 'zone_type', 'purdue_level', 'parent', 'sl_target', 'sl_achieved', 'accountable',
            'wireless', 'temporary_devices', 'devices', 'virtual_machines', 'prefixes', 'tenant_group', 'tenant',
            'description', 'owner', 'comments', 'tags',
        )


class ZoneBulkEditForm(PrimaryModelBulkEditForm):
    site = DynamicModelChoiceField(label=_('Site'), queryset=Site.objects.all(), required=False)
    tenant = DynamicModelChoiceField(label=_('Tenant'), queryset=Tenant.objects.all(), required=False)
    zone_type = forms.ChoiceField(label=_('Zone type'), choices=add_blank_choice(ZoneTypeChoices), required=False)
    purdue_level = forms.ChoiceField(
        label=_('Purdue level'), choices=add_blank_choice(PurdueLevelChoices), required=False,
    )
    sl_target = SLVectorField(label=_('SL-T'))
    sl_achieved = SLVectorField(label=_('SL-A'))
    accountable = DynamicModelChoiceField(label=_('Accountable'), queryset=Contact.objects.all(), required=False)
    parent = DynamicModelChoiceField(label=_('Parent zone'), queryset=Zone.objects.all(), required=False)
    wireless = forms.NullBooleanField(
        label=_('Wireless'), required=False, widget=forms.Select(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )
    temporary_devices = forms.NullBooleanField(
        label=_('Temporarily connected devices'), required=False,
        widget=forms.Select(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )

    model = Zone
    fieldsets = (
        FieldSet('site', 'zone_type', 'purdue_level', 'parent', 'tenant', 'description', name=_('Zone')),
        FieldSet('sl_target', 'sl_achieved', 'accountable', name=_('Security')),
        FieldSet('wireless', 'temporary_devices', name=_('Attributes')),
    )
    nullable_fields = ('site', 'tenant', 'purdue_level', 'parent', 'sl_target', 'sl_achieved', 'accountable',
                       'description', 'comments')


class ZoneImportForm(PrimaryModelImportForm):
    site = CSVModelChoiceField(
        label=_('Site'), queryset=Site.objects.all(), required=False, to_field_name='name',
    )
    tenant = CSVModelChoiceField(
        label=_('Tenant'), queryset=Tenant.objects.all(), required=False, to_field_name='name',
    )
    zone_type = CSVChoiceField(label=_('Zone type'), choices=ZoneTypeChoices, required=False)
    purdue_level = CSVChoiceField(label=_('Purdue level'), choices=PurdueLevelChoices, required=False)
    sl_target = SLVectorField(label=_('SL-T'))
    sl_achieved = SLVectorField(label=_('SL-A'))
    accountable = CSVModelChoiceField(
        label=_('Accountable'), queryset=Contact.objects.all(), required=False, to_field_name='name',
    )
    parent = CSVModelChoiceField(
        label=_('Parent zone'), queryset=Zone.objects.all(), required=False, to_field_name='name',
        help_text=_('Name of a zone of the same site'),
    )

    class Meta:
        model = Zone
        fields = (
            'name', 'slug', 'site', 'tenant', 'zone_type', 'purdue_level', 'parent', 'sl_target', 'sl_achieved',
            'accountable', 'wireless', 'temporary_devices', 'description', 'owner', 'comments', 'tags',
        )

    def __init__(self, data=None, *args, **kwargs):
        super().__init__(data, *args, **kwargs)
        if data:
            _scope_zones_to_site(self, data, ('parent',))


class ZoneFilterForm(TenancyFilterForm, PrimaryModelFilterSetForm):
    model = Zone
    fieldsets = (
        FieldSet('q', 'filter_id', 'tag'),
        FieldSet('site_id', 'zone_type', 'purdue_level', 'parent_id', 'conduit_id', name=_('Zone')),
        FieldSet('has_sl_target', 'sl_gap', 'accountable_id', 'wireless', 'temporary_devices', name=_('Security')),
        FieldSet('device_id', 'virtual_machine_id', name=_('Members')),
        FieldSet('tenant_group_id', 'tenant_id', name=_('Tenancy')),
        FieldSet('owner_group_id', 'owner_id', name=_('Ownership')),
    )
    site_id = DynamicModelMultipleChoiceField(queryset=Site.objects.all(), required=False, label=_('Site'))
    zone_type = forms.MultipleChoiceField(label=_('Zone type'), choices=ZoneTypeChoices, required=False)
    purdue_level = forms.MultipleChoiceField(label=_('Purdue level'), choices=PurdueLevelChoices, required=False)
    parent_id = DynamicModelMultipleChoiceField(queryset=Zone.objects.all(), required=False, label=_('Parent zone'))
    conduit_id = DynamicModelMultipleChoiceField(queryset=Conduit.objects.all(), required=False, label=_('Conduit'))
    has_sl_target = forms.NullBooleanField(
        label=_('Has an SL-T'), required=False, widget=forms.Select(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )
    sl_gap = forms.NullBooleanField(
        label=_('SL-A below SL-T'), required=False, widget=forms.Select(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )
    accountable_id = DynamicModelMultipleChoiceField(
        queryset=Contact.objects.all(), required=False, label=_('Accountable'),
    )
    wireless = forms.NullBooleanField(
        label=_('Wireless'), required=False, widget=forms.Select(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )
    temporary_devices = forms.NullBooleanField(
        label=_('Temporarily connected devices'), required=False,
        widget=forms.Select(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )
    device_id = DynamicModelMultipleChoiceField(queryset=Device.objects.all(), required=False, label=_('Device'))
    virtual_machine_id = DynamicModelMultipleChoiceField(
        queryset=VirtualMachine.objects.all(), required=False, label=_('Virtual machine'),
    )
    tag = TagFilterField(model)


#
# Conduits
#

class ConduitForm(PrimaryModelForm):
    site = DynamicModelChoiceField(label=_('Site'), queryset=Site.objects.all(), required=False)
    zones = DynamicModelMultipleChoiceField(
        label=_('Zones'), queryset=Zone.objects.all(), query_params={'site_id': '$site'},
        help_text=_('The zones this conduit joins (two or more)'),
    )
    sl_target = SLVectorField(label=_('SL-T'))
    sl_achieved = SLVectorField(label=_('SL-A'))
    accountable = DynamicModelChoiceField(label=_('Accountable'), queryset=Contact.objects.all(), required=False)
    enforcing_devices = DynamicModelMultipleChoiceField(
        label=_('Enforcing devices'), queryset=Device.objects.all(), required=False,
        help_text=_('Firewalls, data diodes, gateways'),
    )
    enforcing_virtual_machines = DynamicModelMultipleChoiceField(
        label=_('Enforcing virtual machines'), queryset=VirtualMachine.objects.all(), required=False,
    )

    fieldsets = (
        FieldSet('name', 'site', 'zones', 'description', 'tags', name=_('Conduit')),
        FieldSet('sl_target', 'sl_achieved', 'accountable', name=_('Security')),
        FieldSet('enforcing_devices', 'enforcing_virtual_machines', name=_('Enforced by')),
    )

    class Meta:
        model = Conduit
        fields = (
            'name', 'site', 'zones', 'sl_target', 'sl_achieved', 'accountable', 'enforcing_devices',
            'enforcing_virtual_machines', 'description', 'owner', 'comments', 'tags',
        )

    def clean(self):
        super().clean()
        zones = self.cleaned_data.get('zones')
        if zones is not None and len(zones) < 2:
            raise forms.ValidationError({'zones': _('A conduit joins two or more zones.')})


class ConduitBulkEditForm(PrimaryModelBulkEditForm):
    site = DynamicModelChoiceField(label=_('Site'), queryset=Site.objects.all(), required=False)
    sl_target = SLVectorField(label=_('SL-T'))
    sl_achieved = SLVectorField(label=_('SL-A'))
    accountable = DynamicModelChoiceField(label=_('Accountable'), queryset=Contact.objects.all(), required=False)

    model = Conduit
    fieldsets = (
        FieldSet('site', 'sl_target', 'sl_achieved', 'accountable', 'description'),
    )
    nullable_fields = ('site', 'sl_target', 'sl_achieved', 'accountable', 'description', 'comments')


class ConduitImportForm(PrimaryModelImportForm):
    site = CSVModelChoiceField(
        label=_('Site'), queryset=Site.objects.all(), required=False, to_field_name='name',
        help_text=_('Zone names are looked up within this site'),
    )
    zones = CSVModelMultipleChoiceField(
        label=_('Zones'), queryset=Zone.objects.all(), to_field_name='name',
        help_text=_('Comma-separated zone names, in double quotes'),
    )
    sl_target = SLVectorField(label=_('SL-T'))
    sl_achieved = SLVectorField(label=_('SL-A'))
    accountable = CSVModelChoiceField(
        label=_('Accountable'), queryset=Contact.objects.all(), required=False, to_field_name='name',
    )
    enforcing_devices = CSVModelMultipleChoiceField(
        label=_('Enforcing devices'), queryset=Device.objects.all(), required=False, to_field_name='name',
        help_text=_('Comma-separated device names, in double quotes'),
    )

    class Meta:
        model = Conduit
        fields = (
            'name', 'site', 'zones', 'sl_target', 'sl_achieved', 'accountable', 'enforcing_devices', 'description',
            'owner', 'comments', 'tags',
        )

    def __init__(self, data=None, *args, **kwargs):
        super().__init__(data, *args, **kwargs)
        if data:
            _scope_zones_to_site(self, data, ('zones',))

    def clean(self):
        super().clean()
        zones = self.cleaned_data.get('zones')
        if zones is not None and len(zones) < 2:
            raise forms.ValidationError({'zones': _('A conduit joins two or more zones.')})


class ConduitFilterForm(PrimaryModelFilterSetForm):
    model = Conduit
    fieldsets = (
        FieldSet('q', 'filter_id', 'tag'),
        FieldSet('site_id', 'zone_id', 'has_sl_target', 'sl_gap', 'accountable_id', name=_('Conduit')),
        FieldSet('enforcing_device_id', 'enforcing_virtual_machine_id', name=_('Enforced by')),
        FieldSet('owner_group_id', 'owner_id', name=_('Ownership')),
    )
    site_id = DynamicModelMultipleChoiceField(queryset=Site.objects.all(), required=False, label=_('Site'))
    zone_id = DynamicModelMultipleChoiceField(queryset=Zone.objects.all(), required=False, label=_('Zone'))
    has_sl_target = forms.NullBooleanField(
        label=_('Has an SL-T'), required=False, widget=forms.Select(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )
    sl_gap = forms.NullBooleanField(
        label=_('SL-A below SL-T'), required=False, widget=forms.Select(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )
    accountable_id = DynamicModelMultipleChoiceField(
        queryset=Contact.objects.all(), required=False, label=_('Accountable'),
    )
    enforcing_device_id = DynamicModelMultipleChoiceField(
        queryset=Device.objects.all(), required=False, label=_('Enforcing device'),
    )
    enforcing_virtual_machine_id = DynamicModelMultipleChoiceField(
        queryset=VirtualMachine.objects.all(), required=False, label=_('Enforcing virtual machine'),
    )
    tag = TagFilterField(model)


#
# Flows
#

class FlowForm(PrimaryModelForm):
    source_zone = DynamicModelChoiceField(label=_('Source zone'), queryset=Zone.objects.all())
    destination_zone = DynamicModelChoiceField(label=_('Destination zone'), queryset=Zone.objects.all())
    conduit = DynamicModelChoiceField(
        label=_('Conduit'), queryset=Conduit.objects.all(), required=False,
        query_params={'zone_id': '$source_zone'},
    )
    protocol = forms.ChoiceField(label=_('Protocol'), choices=add_blank_choice(FlowProtocolChoices), required=False)
    port_mappings = PortMappingField(label=_('Ports'), required=False)
    access = forms.MultipleChoiceField(
        label=_('Access'), choices=AccessChoices, required=False,
        help_text=Flow._meta.get_field('access').help_text,
    )
    decided_by = DynamicModelChoiceField(label=_('Decided by'), queryset=Contact.objects.all(), required=False)

    fieldsets = (
        FieldSet('name', 'source_zone', 'destination_zone', 'conduit', 'description', 'tags', name=_('Flow')),
        FieldSet('protocol', 'port_mappings', 'access', 'remote_access', name=_('Traffic')),
        FieldSet('allowed', 'decided_by', 'decided_on', 'review_by', 'expires', name=_('Verdict')),
        FieldSet('first_seen', 'last_seen', 'evidence', name=_('Evidence')),
    )

    class Meta:
        model = Flow
        fields = (
            'name', 'source_zone', 'destination_zone', 'conduit', 'protocol', 'port_mappings', 'access',
            'remote_access', 'allowed', 'decided_by', 'decided_on', 'review_by', 'expires', 'first_seen', 'last_seen',
            'evidence', 'description', 'owner', 'comments', 'tags',
        )
        widgets = {
            'decided_on': DatePicker(),
            'review_by': DatePicker(),
            'expires': DatePicker(),
            'first_seen': DateTimePicker(),
            'last_seen': DateTimePicker(),
            'evidence': forms.Textarea(attrs={'rows': 3}),
        }


class FlowBulkEditForm(PrimaryModelBulkEditForm):
    conduit = DynamicModelChoiceField(label=_('Conduit'), queryset=Conduit.objects.all(), required=False)
    protocol = forms.ChoiceField(label=_('Protocol'), choices=add_blank_choice(FlowProtocolChoices), required=False)
    remote_access = forms.NullBooleanField(
        label=_('Remote access'), required=False, widget=forms.Select(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )
    allowed = forms.ChoiceField(label=_('Allowed'), choices=add_blank_choice(FlowAllowedChoices), required=False)
    decided_by = DynamicModelChoiceField(label=_('Decided by'), queryset=Contact.objects.all(), required=False)
    decided_on = forms.DateField(label=_('Decided on'), required=False, widget=DatePicker())
    review_by = forms.DateField(label=_('Review by'), required=False, widget=DatePicker())
    expires = forms.DateField(label=_('Expires'), required=False, widget=DatePicker())

    model = Flow
    fieldsets = (
        FieldSet('conduit', 'protocol', 'remote_access', 'description', name=_('Flow')),
        FieldSet('allowed', 'decided_by', 'decided_on', 'review_by', 'expires', name=_('Verdict')),
    )
    nullable_fields = ('conduit', 'protocol', 'decided_by', 'review_by', 'expires', 'description', 'comments')


class FlowImportForm(ServicePortMappingsImportMixin, PrimaryModelImportForm):
    site = CSVModelChoiceField(
        label=_('Site'), queryset=Site.objects.all(), required=False, to_field_name='name',
        help_text=_('Site of the zones and conduit; their names are looked up within this site'),
    )
    source_zone = CSVModelChoiceField(label=_('Source zone'), queryset=Zone.objects.all(), to_field_name='name')
    destination_zone = CSVModelChoiceField(
        label=_('Destination zone'), queryset=Zone.objects.all(), to_field_name='name',
    )
    conduit = CSVModelChoiceField(
        label=_('Conduit'), queryset=Conduit.objects.all(), required=False, to_field_name='name',
    )
    protocol = CSVChoiceField(label=_('Protocol'), choices=FlowProtocolChoices, required=False)
    port_mappings = SimpleArrayField(
        base_field=forms.CharField(), label=_('Ports'), required=False,
        help_text=_('Comma-separated protocol/port pairs in double quotes, e.g. "tcp/102,udp/2222"'),
    )
    access = CSVMultipleChoiceField(
        label=_('Access'), choices=AccessChoices, required=False,
        help_text=_('Comma-separated, in double quotes, e.g. "read,write"'),
    )
    allowed = CSVChoiceField(label=_('Allowed'), choices=FlowAllowedChoices, required=False)
    decided_by = CSVModelChoiceField(
        label=_('Decided by'), queryset=Contact.objects.all(), required=False, to_field_name='name',
    )

    class Meta:
        model = Flow
        fields = (
            'site', 'name', 'source_zone', 'destination_zone', 'conduit', 'protocol', 'port_mappings', 'access',
            'remote_access', 'allowed', 'decided_by', 'decided_on', 'review_by', 'expires', 'first_seen', 'last_seen',
            'evidence', 'description', 'owner', 'comments', 'tags',
        )

    def __init__(self, data=None, *args, **kwargs):
        super().__init__(data, *args, **kwargs)
        if data:
            _scope_zones_to_site(self, data, ('source_zone', 'destination_zone', 'conduit'))


class FlowFilterForm(PrimaryModelFilterSetForm):
    model = Flow
    fieldsets = (
        FieldSet('q', 'filter_id', 'tag'),
        FieldSet('site_id', 'zone_id', 'source_zone_id', 'destination_zone_id', 'conduit_id', 'has_conduit',
                 name=_('Zones')),
        FieldSet('protocol', 'port', 'access', 'modifying', 'remote_access', name=_('Traffic')),
        FieldSet('allowed', 'decided_by_id', 'expired', 'review_due', 'stale', name=_('Verdict')),
        FieldSet('hop_device_id', 'hop_virtual_machine_id', 'hop_tunnel_id', name=_('Path')),
        FieldSet('owner_group_id', 'owner_id', name=_('Ownership')),
    )
    site_id = DynamicModelMultipleChoiceField(queryset=Site.objects.all(), required=False, label=_('Site'))
    zone_id = DynamicModelMultipleChoiceField(queryset=Zone.objects.all(), required=False, label=_('Zone'))
    source_zone_id = DynamicModelMultipleChoiceField(
        queryset=Zone.objects.all(), required=False, label=_('Source zone'),
    )
    destination_zone_id = DynamicModelMultipleChoiceField(
        queryset=Zone.objects.all(), required=False, label=_('Destination zone'),
    )
    conduit_id = DynamicModelMultipleChoiceField(queryset=Conduit.objects.all(), required=False, label=_('Conduit'))
    has_conduit = forms.NullBooleanField(
        label=_('Has a conduit'), required=False, widget=forms.Select(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )
    protocol = forms.MultipleChoiceField(label=_('Protocol'), choices=FlowProtocolChoices, required=False)
    port = forms.IntegerField(label=_('Port'), min_value=1, max_value=65535, required=False)
    access = forms.MultipleChoiceField(label=_('Access'), choices=AccessChoices, required=False)
    modifying = forms.NullBooleanField(
        label=_('Writes, controls or programs'), required=False,
        widget=forms.Select(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )
    remote_access = forms.NullBooleanField(
        label=_('Remote access'), required=False, widget=forms.Select(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )
    allowed = forms.MultipleChoiceField(label=_('Allowed'), choices=FlowAllowedChoices, required=False)
    decided_by_id = DynamicModelMultipleChoiceField(
        queryset=Contact.objects.all(), required=False, label=_('Decided by'),
    )
    expired = forms.NullBooleanField(
        label=_('Allowed, but expired'), required=False, widget=forms.Select(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )
    review_due = forms.NullBooleanField(
        label=_('Review due'), required=False, widget=forms.Select(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )
    stale = forms.NullBooleanField(
        label=_('Not seen recently'), required=False, widget=forms.Select(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )
    hop_device_id = DynamicModelMultipleChoiceField(
        queryset=Device.objects.all(), required=False, label=_('Runs through device'),
    )
    hop_virtual_machine_id = DynamicModelMultipleChoiceField(
        queryset=VirtualMachine.objects.all(), required=False, label=_('Runs through virtual machine'),
    )
    hop_tunnel_id = DynamicModelMultipleChoiceField(
        queryset=Tunnel.objects.all(), required=False, label=_('Runs through tunnel'),
    )
    tag = TagFilterField(model)


#
# Flow hops
#

class FlowHopForm(PrimaryModelForm):
    flow = DynamicModelChoiceField(label=_('Flow'), queryset=Flow.objects.all())
    device = DynamicModelChoiceField(label=_('Device'), queryset=Device.objects.all(), required=False)
    virtual_machine = DynamicModelChoiceField(
        label=_('Virtual machine'), queryset=VirtualMachine.objects.all(), required=False,
    )
    tunnel = DynamicModelChoiceField(label=_('Tunnel'), queryset=Tunnel.objects.all(), required=False)

    fieldsets = (
        FieldSet('flow', 'position', 'description', 'tags', name=_('Hop')),
        FieldSet('device', 'virtual_machine', 'tunnel', name=_('Runs through (one of)')),
    )

    class Meta:
        model = FlowHop
        fields = ('flow', 'position', 'device', 'virtual_machine', 'tunnel', 'description', 'owner', 'comments', 'tags')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A new hop goes after the flow's last one
        flow_id = self.initial.get('flow')
        if not self.instance.pk and flow_id and not self.initial.get('position'):
            last = FlowHop.objects.filter(flow_id=flow_id).order_by('-position').values_list('position', flat=True)
            self.initial['position'] = (last.first() or 0) + 1


class FlowHopBulkEditForm(PrimaryModelBulkEditForm):
    model = FlowHop
    fieldsets = (
        FieldSet('description'),
    )
    nullable_fields = ('description', 'comments')


class FlowHopImportForm(PrimaryModelImportForm):
    flow = CSVModelChoiceField(label=_('Flow'), queryset=Flow.objects.all(), to_field_name='pk',
                               help_text=_('Flow ID'))
    device = CSVModelChoiceField(label=_('Device'), queryset=Device.objects.all(), required=False,
                                 to_field_name='name')
    virtual_machine = CSVModelChoiceField(label=_('Virtual machine'), queryset=VirtualMachine.objects.all(),
                                          required=False, to_field_name='name')
    tunnel = CSVModelChoiceField(label=_('Tunnel'), queryset=Tunnel.objects.all(), required=False,
                                 to_field_name='name')

    class Meta:
        model = FlowHop
        fields = ('flow', 'position', 'device', 'virtual_machine', 'tunnel', 'description', 'owner', 'comments', 'tags')


class FlowHopFilterForm(PrimaryModelFilterSetForm):
    model = FlowHop
    fieldsets = (
        FieldSet('q', 'filter_id', 'tag'),
        FieldSet('flow_id', 'device_id', 'virtual_machine_id', 'tunnel_id', name=_('Hop')),
    )
    flow_id = DynamicModelMultipleChoiceField(queryset=Flow.objects.all(), required=False, label=_('Flow'))
    device_id = DynamicModelMultipleChoiceField(queryset=Device.objects.all(), required=False, label=_('Device'))
    virtual_machine_id = DynamicModelMultipleChoiceField(
        queryset=VirtualMachine.objects.all(), required=False, label=_('Virtual machine'),
    )
    tunnel_id = DynamicModelMultipleChoiceField(queryset=Tunnel.objects.all(), required=False, label=_('Tunnel'))
    tag = TagFilterField(model)


#
# Risk assessments
#

class RiskAssessmentForm(PrimaryModelForm):
    zone = DynamicModelChoiceField(label=_('Zone'), queryset=Zone.objects.all(), required=False)
    conduit = DynamicModelChoiceField(label=_('Conduit'), queryset=Conduit.objects.all(), required=False)
    assessed_by = DynamicModelChoiceField(label=_('Assessed by'), queryset=Contact.objects.all(), required=False)
    approved_by = DynamicModelChoiceField(label=_('Approved by'), queryset=Contact.objects.all(), required=False)

    fieldsets = (
        FieldSet('zone', 'conduit', 'kind', 'status', 'description', 'tags', name=_('Risk assessment')),
        FieldSet('assessed_on', 'assessed_by', 'approved_on', 'approved_by', 'next_review', 'method', 'document',
                 name=_('Record')),
        FieldSet('threats', 'vulnerabilities', 'consequences', 'unmitigated_risk', name=_('Risk')),
        FieldSet('countermeasures', 'residual_risk', 'tolerable_risk', name=_('Treatment')),
    )

    class Meta:
        model = RiskAssessment
        fields = (
            'zone', 'conduit', 'kind', 'status', 'assessed_on', 'assessed_by', 'approved_on', 'approved_by',
            'next_review', 'method', 'document', 'threats', 'vulnerabilities', 'consequences', 'unmitigated_risk',
            'countermeasures', 'residual_risk', 'tolerable_risk', 'description', 'owner', 'comments', 'tags',
        )
        widgets = {
            'assessed_on': DatePicker(),
            'approved_on': DatePicker(),
            'next_review': DatePicker(),
            'threats': forms.Textarea(attrs={'rows': 3}),
            'vulnerabilities': forms.Textarea(attrs={'rows': 3}),
            'consequences': forms.Textarea(attrs={'rows': 3}),
            'countermeasures': forms.Textarea(attrs={'rows': 3}),
        }


class RiskAssessmentBulkEditForm(PrimaryModelBulkEditForm):
    status = forms.ChoiceField(
        label=_('Status'), choices=add_blank_choice(RiskAssessmentStatusChoices), required=False,
    )
    approved_by = DynamicModelChoiceField(label=_('Approved by'), queryset=Contact.objects.all(), required=False)
    approved_on = forms.DateField(label=_('Approved on'), required=False, widget=DatePicker())
    next_review = forms.DateField(label=_('Next review'), required=False, widget=DatePicker())
    tolerable_risk = forms.ChoiceField(
        label=_('Tolerable risk'), choices=add_blank_choice(RiskLevelChoices), required=False,
    )

    model = RiskAssessment
    fieldsets = (
        FieldSet('status', 'approved_by', 'approved_on', 'next_review', 'tolerable_risk', 'description'),
    )
    nullable_fields = ('approved_by', 'approved_on', 'next_review', 'description', 'comments')


class RiskAssessmentImportForm(PrimaryModelImportForm):
    site = CSVModelChoiceField(
        label=_('Site'), queryset=Site.objects.all(), required=False, to_field_name='name',
        help_text=_('Site of the zone or conduit; its name is looked up within this site'),
    )
    zone = CSVModelChoiceField(label=_('Zone'), queryset=Zone.objects.all(), required=False, to_field_name='name')
    conduit = CSVModelChoiceField(
        label=_('Conduit'), queryset=Conduit.objects.all(), required=False, to_field_name='name',
    )
    kind = CSVChoiceField(label=_('Kind'), choices=RiskAssessmentKindChoices, required=False)
    status = CSVChoiceField(label=_('Status'), choices=RiskAssessmentStatusChoices, required=False)
    assessed_by = CSVModelChoiceField(
        label=_('Assessed by'), queryset=Contact.objects.all(), required=False, to_field_name='name',
    )
    approved_by = CSVModelChoiceField(
        label=_('Approved by'), queryset=Contact.objects.all(), required=False, to_field_name='name',
    )
    unmitigated_risk = CSVChoiceField(label=_('Unmitigated risk'), choices=RiskLevelChoices, required=False)
    residual_risk = CSVChoiceField(label=_('Residual risk'), choices=RiskLevelChoices, required=False)
    tolerable_risk = CSVChoiceField(label=_('Tolerable risk'), choices=RiskLevelChoices, required=False)

    class Meta:
        model = RiskAssessment
        fields = (
            'site', 'zone', 'conduit', 'kind', 'status', 'assessed_on', 'assessed_by', 'approved_on', 'approved_by',
            'next_review', 'method', 'document', 'threats', 'vulnerabilities', 'consequences', 'unmitigated_risk',
            'countermeasures', 'residual_risk', 'tolerable_risk', 'description', 'owner', 'comments', 'tags',
        )

    def __init__(self, data=None, *args, **kwargs):
        super().__init__(data, *args, **kwargs)
        if data:
            _scope_zones_to_site(self, data, ('zone', 'conduit'))


class RiskAssessmentFilterForm(PrimaryModelFilterSetForm):
    model = RiskAssessment
    fieldsets = (
        FieldSet('q', 'filter_id', 'tag'),
        FieldSet('site_id', 'zone_id', 'conduit_id', 'kind', 'status', name=_('Risk assessment')),
        FieldSet('residual_risk', 'tolerable_risk', 'residual_above_tolerable', 'review_due', name=_('Risk')),
        FieldSet('assessed_by_id', 'approved_by_id', name=_('People')),
    )
    site_id = DynamicModelMultipleChoiceField(queryset=Site.objects.all(), required=False, label=_('Site'))
    zone_id = DynamicModelMultipleChoiceField(queryset=Zone.objects.all(), required=False, label=_('Zone'))
    conduit_id = DynamicModelMultipleChoiceField(queryset=Conduit.objects.all(), required=False, label=_('Conduit'))
    kind = forms.MultipleChoiceField(label=_('Kind'), choices=RiskAssessmentKindChoices, required=False)
    status = forms.MultipleChoiceField(label=_('Status'), choices=RiskAssessmentStatusChoices, required=False)
    residual_risk = forms.MultipleChoiceField(label=_('Residual risk'), choices=RiskLevelChoices, required=False)
    tolerable_risk = forms.MultipleChoiceField(label=_('Tolerable risk'), choices=RiskLevelChoices, required=False)
    residual_above_tolerable = forms.NullBooleanField(
        label=_('Residual above tolerable'), required=False, widget=forms.Select(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )
    review_due = forms.NullBooleanField(
        label=_('Review due'), required=False, widget=forms.Select(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )
    assessed_by_id = DynamicModelMultipleChoiceField(
        queryset=Contact.objects.all(), required=False, label=_('Assessed by'),
    )
    approved_by_id = DynamicModelMultipleChoiceField(
        queryset=Contact.objects.all(), required=False, label=_('Approved by'),
    )
    tag = TagFilterField(model)


#
# Fieldbuses
#

class FieldbusForm(PrimaryModelForm):
    site = DynamicModelChoiceField(label=_('Site'), queryset=Site.objects.all(), required=False)
    zone = DynamicModelChoiceField(
        label=_('Zone'), queryset=Zone.objects.all(), required=False, query_params={'site_id': '$site'},
    )
    protocol = forms.ChoiceField(
        label=_('Protocol'), choices=add_blank_choice(IndustrialProtocolChoices), required=False,
    )
    gateway = DynamicModelChoiceField(
        label=_('Gateway'), queryset=Device.objects.all(), required=False, query_params={'site_id': '$site'},
    )

    fieldsets = (
        FieldSet('name', 'site', 'zone', 'description', 'tags', name=_('Fieldbus')),
        FieldSet('medium', 'protocol', 'gateway', name=_('Bus')),
    )

    class Meta:
        model = Fieldbus
        fields = (
            'name', 'site', 'zone', 'medium', 'protocol', 'gateway', 'description', 'owner', 'comments', 'tags',
        )


class FieldbusBulkEditForm(PrimaryModelBulkEditForm):
    site = DynamicModelChoiceField(label=_('Site'), queryset=Site.objects.all(), required=False)
    zone = DynamicModelChoiceField(label=_('Zone'), queryset=Zone.objects.all(), required=False)
    medium = forms.ChoiceField(label=_('Medium'), choices=add_blank_choice(FieldbusMediumChoices), required=False)
    protocol = forms.ChoiceField(
        label=_('Protocol'), choices=add_blank_choice(IndustrialProtocolChoices), required=False,
    )

    model = Fieldbus
    fieldsets = (
        FieldSet('site', 'zone', 'medium', 'protocol', 'description'),
    )
    nullable_fields = ('site', 'zone', 'protocol', 'description', 'comments')


class FieldbusImportForm(PrimaryModelImportForm):
    site = CSVModelChoiceField(
        label=_('Site'), queryset=Site.objects.all(), required=False, to_field_name='name',
    )
    zone = CSVModelChoiceField(label=_('Zone'), queryset=Zone.objects.all(), required=False, to_field_name='name')
    medium = CSVChoiceField(label=_('Medium'), choices=FieldbusMediumChoices)
    protocol = CSVChoiceField(label=_('Protocol'), choices=IndustrialProtocolChoices, required=False)
    gateway = CSVModelChoiceField(
        label=_('Gateway'), queryset=Device.objects.all(), required=False, to_field_name='name',
    )

    class Meta:
        model = Fieldbus
        fields = (
            'name', 'site', 'zone', 'medium', 'protocol', 'gateway', 'description', 'owner', 'comments', 'tags',
        )


class FieldbusFilterForm(PrimaryModelFilterSetForm):
    model = Fieldbus
    fieldsets = (
        FieldSet('q', 'filter_id', 'tag'),
        FieldSet('site_id', 'zone_id', 'medium', 'protocol', 'gateway_id', name=_('Fieldbus')),
    )
    site_id = DynamicModelMultipleChoiceField(queryset=Site.objects.all(), required=False, label=_('Site'))
    zone_id = DynamicModelMultipleChoiceField(queryset=Zone.objects.all(), required=False, label=_('Zone'))
    medium = forms.MultipleChoiceField(label=_('Medium'), choices=FieldbusMediumChoices, required=False)
    protocol = forms.MultipleChoiceField(label=_('Protocol'), choices=IndustrialProtocolChoices, required=False)
    gateway_id = DynamicModelMultipleChoiceField(
        queryset=Device.objects.all(), required=False, label=_('Gateway'),
    )
    tag = TagFilterField(model)


#
# Industrial services
#

class IndustrialServiceForm(PrimaryModelForm):
    device = DynamicModelChoiceField(label=_('Device'), queryset=Device.objects.all(), required=False)
    virtual_machine = DynamicModelChoiceField(
        label=_('Virtual machine'), queryset=VirtualMachine.objects.all(), required=False,
    )
    service = DynamicModelChoiceField(
        label=_('Application service'), queryset=Service.objects.all(), required=False,
        query_params={'device_id': '$device', 'virtual_machine_id': '$virtual_machine'},
        help_text=_('The NetBox application service with the ports and IP addresses'),
    )
    fieldbus = DynamicModelChoiceField(label=_('Fieldbus'), queryset=Fieldbus.objects.all(), required=False)

    fieldsets = (
        FieldSet('device', 'virtual_machine', 'protocol', 'role', 'description', 'tags', name=_('Industrial service')),
        FieldSet('service', name=_('Network')),
        FieldSet('fieldbus', 'address', name=_('Fieldbus')),
        FieldSet('evidence', name=_('Evidence')),
    )

    class Meta:
        model = IndustrialService
        fields = (
            'device', 'virtual_machine', 'protocol', 'role', 'service', 'fieldbus', 'address', 'evidence',
            'description', 'owner', 'comments', 'tags',
        )
        widgets = {
            'evidence': forms.Textarea(attrs={'rows': 3}),
        }


class IndustrialServiceBulkEditForm(PrimaryModelBulkEditForm):
    protocol = forms.ChoiceField(
        label=_('Protocol'), choices=add_blank_choice(IndustrialProtocolChoices), required=False,
    )
    role = forms.ChoiceField(label=_('Role'), choices=add_blank_choice(ServiceRoleChoices), required=False)
    fieldbus = DynamicModelChoiceField(label=_('Fieldbus'), queryset=Fieldbus.objects.all(), required=False)
    address = forms.CharField(label=_('Address'), max_length=50, required=False)

    model = IndustrialService
    fieldsets = (
        FieldSet('protocol', 'role', 'fieldbus', 'address', 'description'),
    )
    nullable_fields = ('fieldbus', 'address', 'description', 'comments')


class IndustrialServiceImportForm(PrimaryModelImportForm):
    device = CSVModelChoiceField(
        label=_('Device'), queryset=Device.objects.all(), required=False, to_field_name='name',
    )
    virtual_machine = CSVModelChoiceField(
        label=_('Virtual machine'), queryset=VirtualMachine.objects.all(), required=False, to_field_name='name',
    )
    protocol = CSVChoiceField(label=_('Protocol'), choices=IndustrialProtocolChoices)
    role = CSVChoiceField(label=_('Role'), choices=ServiceRoleChoices, required=False)
    service = CSVModelChoiceField(
        label=_('Application service'), queryset=Service.objects.all(), required=False, to_field_name='name',
        help_text=_('Name of an application service on the same device or VM'),
    )
    fieldbus = CSVModelChoiceField(
        label=_('Fieldbus'), queryset=Fieldbus.objects.all(), required=False, to_field_name='name',
    )

    class Meta:
        model = IndustrialService
        fields = (
            'device', 'virtual_machine', 'protocol', 'role', 'service', 'fieldbus', 'address', 'evidence',
            'description', 'owner', 'comments', 'tags',
        )

    def __init__(self, data=None, *args, **kwargs):
        super().__init__(data, *args, **kwargs)
        if data and (data.get('device') or data.get('virtual_machine')):
            # Service names are only unique per device or VM
            if data.get('device'):
                services = Service.objects.filter(device__name=data.get('device'))
            else:
                services = Service.objects.filter(virtual_machine__name=data.get('virtual_machine'))
            self.fields['service'].queryset = services


class IndustrialServiceFilterForm(PrimaryModelFilterSetForm):
    model = IndustrialService
    fieldsets = (
        FieldSet('q', 'filter_id', 'tag'),
        FieldSet('protocol', 'role', 'port', name=_('Service')),
        FieldSet('site_id', 'zone_id', 'device_id', 'virtual_machine_id', 'fieldbus_id', name=_('Where')),
        FieldSet('owner_group_id', 'owner_id', name=_('Ownership')),
    )
    protocol = forms.MultipleChoiceField(label=_('Protocol'), choices=IndustrialProtocolChoices, required=False)
    role = forms.MultipleChoiceField(label=_('Role'), choices=ServiceRoleChoices, required=False)
    port = forms.IntegerField(label=_('Port'), min_value=1, max_value=65535, required=False)
    site_id = DynamicModelMultipleChoiceField(queryset=Site.objects.all(), required=False, label=_('Site'))
    zone_id = DynamicModelMultipleChoiceField(queryset=Zone.objects.all(), required=False, label=_('Zone'))
    device_id = DynamicModelMultipleChoiceField(queryset=Device.objects.all(), required=False, label=_('Device'))
    virtual_machine_id = DynamicModelMultipleChoiceField(
        queryset=VirtualMachine.objects.all(), required=False, label=_('Virtual machine'),
    )
    fieldbus_id = DynamicModelMultipleChoiceField(
        queryset=Fieldbus.objects.all(), required=False, label=_('Fieldbus'),
    )
    tag = TagFilterField(model)


#
# Access map
#

class AccessMapFilterForm(forms.Form):
    site_id = DynamicModelChoiceField(queryset=Site.objects.all(), required=False, label=_('Site'))
    max_level = forms.ChoiceField(
        label=_('Into zones at Purdue level up to'),
        choices=[(v, label) for v, label in PurdueLevelChoices.CHOICES],
        required=False,
    )


class ChecksFilterForm(forms.Form):
    site_id = DynamicModelChoiceField(queryset=Site.objects.all(), required=False, label=_('Site'))
    severity = forms.MultipleChoiceField(
        label=_('Severity'), required=False,
        choices=(('error', _('Error')), ('warning', _('Warning')), ('info', _('Info'))),
    )


class PluginSettingsForm(forms.ModelForm):
    """The settings page: which branch the import and demo commands use, and whether main is off limits."""
    default_branch = forms.ChoiceField(label=_('Default branch'), required=False)

    class Meta:
        model = PluginSettings
        fields = ('branching_enabled', 'default_branch', 'protect_main')
        labels = {
            'branching_enabled': _('Use a branch for imports'),
            'protect_main': _('Refuse imports into main'),
        }

    def __init__(self, *args, **kwargs):
        from .branching import branch_names
        super().__init__(*args, **kwargs)
        ready = branch_names(ready_only=True)
        choices = [('', '---------')] + [(name, name) for name in ready]
        current = self.instance.default_branch
        if current and current not in ready:
            # Keep a branch that was merged or deleted visible, so the page says what is set
            choices.append((current, _('{name} (no longer ready)').format(name=current)))
        self.fields['default_branch'].choices = choices
        self.fields['default_branch'].help_text = _(
            'Commands without --branch or --main run here. Only branches that are ready are listed.'
        )

    def clean_default_branch(self):
        from .branching import branch_names
        name = self.cleaned_data['default_branch']
        if name and name != self.instance.default_branch and name not in branch_names(ready_only=True):
            raise forms.ValidationError(_('No branch of that name is ready.'))
        return name
