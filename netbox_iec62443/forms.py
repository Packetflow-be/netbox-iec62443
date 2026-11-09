from django import forms
from django.utils.translation import gettext_lazy as _

from dcim.models import Device, Interface, Site
from ipam.models import Prefix
from netbox.forms import (
    PrimaryModelBulkEditForm,
    PrimaryModelFilterSetForm,
    PrimaryModelForm,
    PrimaryModelImportForm,
)
from tenancy.forms import TenancyFilterForm, TenancyForm
from tenancy.models import Tenant
from utilities.forms import add_blank_choice
from utilities.forms.constants import BOOLEAN_WITH_BLANK_CHOICES
from utilities.forms.fields import (
    CSVChoiceField,
    CSVModelChoiceField,
    CSVTypedChoiceField,
    DynamicModelChoiceField,
    DynamicModelMultipleChoiceField,
    NumericArrayField,
    SlugField,
    TagFilterField,
)
from utilities.forms.rendering import FieldSet
from virtualization.models import VirtualMachine

from .choices import (
    ConduitAllowedChoices,
    ConduitDirectionChoices,
    FieldbusMediumChoices,
    IndustrialProtocolChoices,
    PurdueLevelChoices,
    SecurityLevelChoices,
    ServiceRoleChoices,
)
from .models import Conduit, Fieldbus, IndustrialService, Zone

__all__ = (
    'AccessMapFilterForm',
    'ConduitBulkEditForm',
    'ConduitFilterForm',
    'ConduitForm',
    'ConduitImportForm',
    'FieldbusBulkEditForm',
    'FieldbusFilterForm',
    'FieldbusForm',
    'FieldbusImportForm',
    'IndustrialServiceBulkEditForm',
    'IndustrialServiceFilterForm',
    'IndustrialServiceForm',
    'IndustrialServiceImportForm',
    'ZoneBulkEditForm',
    'ZoneFilterForm',
    'ZoneForm',
    'ZoneImportForm',
)


#
# Zones
#

class ZoneForm(TenancyForm, PrimaryModelForm):
    slug = SlugField()
    site = DynamicModelChoiceField(label=_('Site'), queryset=Site.objects.all(), required=False)
    purdue_level = forms.ChoiceField(
        label=_('Purdue level'), choices=add_blank_choice(PurdueLevelChoices), required=False,
    )
    security_level_target = forms.TypedChoiceField(
        label=_('Security level target (SL-T)'), choices=add_blank_choice(SecurityLevelChoices),
        coerce=int, empty_value=None, required=False,
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
        FieldSet('name', 'slug', 'site', 'purdue_level', 'security_level_target', 'description', 'tags',
                 name=_('Zone')),
        FieldSet('devices', 'virtual_machines', 'prefixes', name=_('Members')),
        FieldSet('tenant_group', 'tenant', name=_('Tenancy')),
    )

    class Meta:
        model = Zone
        fields = (
            'name', 'slug', 'site', 'purdue_level', 'security_level_target', 'devices', 'virtual_machines',
            'prefixes', 'tenant_group', 'tenant', 'description', 'owner', 'comments', 'tags',
        )


class ZoneBulkEditForm(PrimaryModelBulkEditForm):
    site = DynamicModelChoiceField(label=_('Site'), queryset=Site.objects.all(), required=False)
    tenant = DynamicModelChoiceField(label=_('Tenant'), queryset=Tenant.objects.all(), required=False)
    purdue_level = forms.ChoiceField(
        label=_('Purdue level'), choices=add_blank_choice(PurdueLevelChoices), required=False,
    )
    security_level_target = forms.TypedChoiceField(
        label=_('Security level target (SL-T)'), choices=add_blank_choice(SecurityLevelChoices),
        coerce=int, empty_value=None, required=False,
    )

    model = Zone
    fieldsets = (
        FieldSet('site', 'purdue_level', 'security_level_target', 'tenant', 'description'),
    )
    nullable_fields = ('site', 'tenant', 'purdue_level', 'security_level_target', 'description', 'comments')


class ZoneImportForm(PrimaryModelImportForm):
    site = CSVModelChoiceField(
        label=_('Site'), queryset=Site.objects.all(), required=False, to_field_name='name',
    )
    tenant = CSVModelChoiceField(
        label=_('Tenant'), queryset=Tenant.objects.all(), required=False, to_field_name='name',
    )
    purdue_level = CSVChoiceField(label=_('Purdue level'), choices=PurdueLevelChoices, required=False)
    security_level_target = CSVTypedChoiceField(
        label=_('Security level target (SL-T)'), choices=SecurityLevelChoices, coerce=int, empty_value=None,
        required=False,
    )

    class Meta:
        model = Zone
        fields = (
            'name', 'slug', 'site', 'tenant', 'purdue_level', 'security_level_target', 'description', 'owner',
            'comments', 'tags',
        )


class ZoneFilterForm(TenancyFilterForm, PrimaryModelFilterSetForm):
    model = Zone
    fieldsets = (
        FieldSet('q', 'filter_id', 'tag'),
        FieldSet('site_id', 'purdue_level', 'security_level_target', name=_('Zone')),
        FieldSet('device_id', 'virtual_machine_id', name=_('Members')),
        FieldSet('tenant_group_id', 'tenant_id', name=_('Tenancy')),
        FieldSet('owner_group_id', 'owner_id', name=_('Ownership')),
    )
    site_id = DynamicModelMultipleChoiceField(queryset=Site.objects.all(), required=False, label=_('Site'))
    purdue_level = forms.MultipleChoiceField(label=_('Purdue level'), choices=PurdueLevelChoices, required=False)
    security_level_target = forms.MultipleChoiceField(
        label=_('SL-T'), choices=SecurityLevelChoices, required=False,
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
    source_zone = DynamicModelChoiceField(label=_('Source zone'), queryset=Zone.objects.all())
    destination_zone = DynamicModelChoiceField(label=_('Destination zone'), queryset=Zone.objects.all())

    fieldsets = (
        FieldSet('name', 'source_zone', 'destination_zone', 'direction', 'description', 'tags', name=_('Conduit')),
        FieldSet('allowed', 'protocols', 'remote_access', 'via', 'evidence', name=_('Access')),
    )

    class Meta:
        model = Conduit
        fields = (
            'name', 'source_zone', 'destination_zone', 'direction', 'allowed', 'protocols', 'remote_access', 'via',
            'evidence', 'description', 'owner', 'comments', 'tags',
        )
        widgets = {
            'evidence': forms.Textarea(attrs={'rows': 3}),
        }


class ConduitBulkEditForm(PrimaryModelBulkEditForm):
    direction = forms.ChoiceField(
        label=_('Direction'), choices=add_blank_choice(ConduitDirectionChoices), required=False,
    )
    allowed = forms.ChoiceField(
        label=_('Allowed'), choices=add_blank_choice(ConduitAllowedChoices), required=False,
    )
    remote_access = forms.NullBooleanField(
        label=_('Remote access'), required=False, widget=forms.Select(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )
    protocols = forms.CharField(label=_('Protocols / ports'), max_length=200, required=False)
    via = forms.CharField(label=_('Via'), max_length=200, required=False)

    model = Conduit
    fieldsets = (
        FieldSet('direction', 'allowed', 'remote_access', 'protocols', 'via', 'description'),
    )
    nullable_fields = ('protocols', 'via', 'description', 'comments')


class ConduitImportForm(PrimaryModelImportForm):
    site = CSVModelChoiceField(
        label=_('Site'), queryset=Site.objects.all(), required=False, to_field_name='name',
        help_text=_('Site of both zones; zone names are looked up within this site'),
    )
    source_zone = CSVModelChoiceField(label=_('Source zone'), queryset=Zone.objects.all(), to_field_name='name')
    destination_zone = CSVModelChoiceField(
        label=_('Destination zone'), queryset=Zone.objects.all(), to_field_name='name',
    )
    direction = CSVChoiceField(label=_('Direction'), choices=ConduitDirectionChoices, required=False)
    allowed = CSVChoiceField(label=_('Allowed'), choices=ConduitAllowedChoices, required=False)

    class Meta:
        model = Conduit
        fields = (
            'site', 'name', 'source_zone', 'destination_zone', 'direction', 'allowed', 'protocols', 'remote_access',
            'via', 'evidence', 'description', 'owner', 'comments', 'tags',
        )

    def __init__(self, data=None, *args, **kwargs):
        super().__init__(data, *args, **kwargs)
        if data:
            # Zone names are unique per site: scope both lookups to the given site (or to zones without one)
            if data.get('site'):
                params = {'site__name': data.get('site')}
            else:
                params = {'site__isnull': True}
            for field in ('source_zone', 'destination_zone'):
                self.fields[field].queryset = self.fields[field].queryset.filter(**params)


class ConduitFilterForm(PrimaryModelFilterSetForm):
    model = Conduit
    fieldsets = (
        FieldSet('q', 'filter_id', 'tag'),
        FieldSet('site_id', 'zone_id', 'source_zone_id', 'destination_zone_id', name=_('Zones')),
        FieldSet('allowed', 'remote_access', 'direction', name=_('Access')),
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
    allowed = forms.MultipleChoiceField(label=_('Allowed'), choices=ConduitAllowedChoices, required=False)
    direction = forms.MultipleChoiceField(label=_('Direction'), choices=ConduitDirectionChoices, required=False)
    remote_access = forms.NullBooleanField(
        label=_('Remote access'), required=False, widget=forms.Select(choices=BOOLEAN_WITH_BLANK_CHOICES),
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
        FieldSet('medium', 'protocol', 'baud_rate', 'frame_format', 'gateway', name=_('Bus')),
    )

    class Meta:
        model = Fieldbus
        fields = (
            'name', 'site', 'zone', 'medium', 'protocol', 'baud_rate', 'frame_format', 'gateway', 'description',
            'owner', 'comments', 'tags',
        )


class FieldbusBulkEditForm(PrimaryModelBulkEditForm):
    site = DynamicModelChoiceField(label=_('Site'), queryset=Site.objects.all(), required=False)
    zone = DynamicModelChoiceField(label=_('Zone'), queryset=Zone.objects.all(), required=False)
    medium = forms.ChoiceField(label=_('Medium'), choices=add_blank_choice(FieldbusMediumChoices), required=False)
    protocol = forms.ChoiceField(
        label=_('Protocol'), choices=add_blank_choice(IndustrialProtocolChoices), required=False,
    )
    baud_rate = forms.IntegerField(label=_('Baud rate'), min_value=1, required=False)
    frame_format = forms.CharField(label=_('Frame format'), max_length=10, required=False)

    model = Fieldbus
    fieldsets = (
        FieldSet('site', 'zone', 'medium', 'protocol', 'baud_rate', 'frame_format', 'description'),
    )
    nullable_fields = ('site', 'zone', 'protocol', 'baud_rate', 'frame_format', 'description', 'comments')


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
            'name', 'site', 'zone', 'medium', 'protocol', 'baud_rate', 'frame_format', 'gateway', 'description',
            'owner', 'comments', 'tags',
        )


class FieldbusFilterForm(PrimaryModelFilterSetForm):
    model = Fieldbus
    fieldsets = (
        FieldSet('q', 'filter_id', 'tag'),
        FieldSet('site_id', 'zone_id', 'medium', 'protocol', 'gateway_id', name=_('Fieldbus')),
        FieldSet('owner_group_id', 'owner_id', name=_('Ownership')),
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
    interface = DynamicModelChoiceField(
        label=_('Interface'), queryset=Interface.objects.all(), required=False,
        query_params={'device_id': '$device'},
    )
    ports = NumericArrayField(
        label=_('Ports'), base_field=forms.IntegerField(min_value=1, max_value=65535), required=False,
        help_text=_('Comma-separated; left empty, the protocol\'s usual ports are filled in'),
    )
    fieldbus = DynamicModelChoiceField(label=_('Fieldbus'), queryset=Fieldbus.objects.all(), required=False)

    fieldsets = (
        FieldSet('device', 'virtual_machine', 'protocol', 'role', 'description', 'tags', name=_('Service')),
        FieldSet('interface', 'ports', name=_('Network')),
        FieldSet('fieldbus', 'address', name=_('Fieldbus')),
        FieldSet('evidence', name=_('Evidence')),
    )

    class Meta:
        model = IndustrialService
        fields = (
            'device', 'virtual_machine', 'protocol', 'role', 'interface', 'ports', 'fieldbus', 'address',
            'evidence', 'description', 'owner', 'comments', 'tags',
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
    interface = CSVModelChoiceField(
        label=_('Interface'), queryset=Interface.objects.all(), required=False, to_field_name='name',
        help_text=_('Interface name on the device'),
    )
    ports = NumericArrayField(
        label=_('Ports'), base_field=forms.IntegerField(min_value=1, max_value=65535), required=False,
    )
    fieldbus = CSVModelChoiceField(
        label=_('Fieldbus'), queryset=Fieldbus.objects.all(), required=False, to_field_name='name',
    )

    class Meta:
        model = IndustrialService
        fields = (
            'device', 'virtual_machine', 'protocol', 'role', 'interface', 'ports', 'fieldbus', 'address',
            'evidence', 'description', 'owner', 'comments', 'tags',
        )

    def __init__(self, data=None, *args, **kwargs):
        super().__init__(data, *args, **kwargs)
        if data and data.get('device'):
            # Interface names are unique per device only
            self.fields['interface'].queryset = Interface.objects.filter(device__name=data.get('device'))


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
