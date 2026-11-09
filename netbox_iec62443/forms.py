from django import forms
from django.utils.translation import gettext_lazy as _

from dcim.models import Device, Site
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
    SlugField,
    TagFilterField,
)
from utilities.forms.rendering import FieldSet
from virtualization.models import VirtualMachine

from .choices import ConduitAllowedChoices, ConduitDirectionChoices, PurdueLevelChoices, SecurityLevelChoices
from .models import Conduit, Zone

__all__ = (
    'AccessMapFilterForm',
    'ConduitBulkEditForm',
    'ConduitFilterForm',
    'ConduitForm',
    'ConduitImportForm',
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
# Access map
#

class AccessMapFilterForm(forms.Form):
    site_id = DynamicModelChoiceField(queryset=Site.objects.all(), required=False, label=_('Site'))
    max_level = forms.ChoiceField(
        label=_('Into zones at Purdue level up to'),
        choices=[(v, label) for v, label in PurdueLevelChoices.CHOICES],
        required=False,
    )
