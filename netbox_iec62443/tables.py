import django_tables2 as tables
from django.utils.translation import gettext_lazy as _

from netbox.tables import PrimaryModelTable, columns
from tenancy.tables import TenancyColumnsMixin

from .models import Conduit, Fieldbus, IndustrialService, Zone

__all__ = ('ConduitTable', 'FieldbusTable', 'IndustrialServiceTable', 'ZoneTable')


class ZoneTable(TenancyColumnsMixin, PrimaryModelTable):
    name = tables.Column(verbose_name=_('Name'), linkify=True)
    site = tables.Column(verbose_name=_('Site'), linkify=True)
    purdue_level = columns.ChoiceFieldColumn(verbose_name=_('Purdue level'))
    security_level_target = tables.Column(verbose_name=_('SL-T'))
    device_count = tables.Column(verbose_name=_('Device count'))
    conduit_count = tables.Column(verbose_name=_('Conduits'))
    devices = columns.ManyToManyColumn(verbose_name=_('Devices'), linkify_item=True)
    virtual_machines = columns.ManyToManyColumn(verbose_name=_('Virtual machines'), linkify_item=True)
    prefixes = columns.ManyToManyColumn(verbose_name=_('Prefixes'), linkify_item=True)
    tags = columns.TagColumn(url_name='plugins:netbox_iec62443:zone_list')

    class Meta(PrimaryModelTable.Meta):
        model = Zone
        fields = (
            'pk', 'id', 'name', 'slug', 'site', 'purdue_level', 'security_level_target', 'device_count',
            'conduit_count', 'devices',
            'virtual_machines', 'prefixes', 'tenant', 'tenant_group', 'description', 'comments', 'tags', 'created',
            'last_updated',
        )
        default_columns = (
            'pk', 'name', 'site', 'purdue_level', 'security_level_target', 'device_count', 'conduit_count', 'prefixes',
        )


class ConduitTable(PrimaryModelTable):
    name = tables.Column(verbose_name=_('Name'), linkify=True)
    source_zone = tables.Column(verbose_name=_('From zone'), linkify=True)
    destination_zone = tables.Column(verbose_name=_('To zone'), linkify=True)
    direction = columns.ChoiceFieldColumn(verbose_name=_('Direction'))
    allowed = columns.ChoiceFieldColumn(verbose_name=_('Allowed'))
    remote_access = columns.BooleanColumn(verbose_name=_('Remote access'))
    tags = columns.TagColumn(url_name='plugins:netbox_iec62443:conduit_list')

    class Meta(PrimaryModelTable.Meta):
        model = Conduit
        fields = (
            'pk', 'id', 'name', 'source_zone', 'destination_zone', 'direction', 'allowed', 'protocols',
            'remote_access', 'via', 'evidence', 'description', 'comments', 'tags', 'created', 'last_updated',
        )
        default_columns = (
            'pk', 'name', 'source_zone', 'destination_zone', 'direction', 'protocols', 'remote_access', 'via',
            'allowed',
        )


class FieldbusTable(PrimaryModelTable):
    name = tables.Column(verbose_name=_('Name'), linkify=True)
    site = tables.Column(verbose_name=_('Site'), linkify=True)
    zone = tables.Column(verbose_name=_('Zone'), linkify=True)
    medium = columns.ChoiceFieldColumn(verbose_name=_('Medium'))
    protocol = columns.ChoiceFieldColumn(verbose_name=_('Protocol'))
    gateway = tables.Column(verbose_name=_('Gateway'), linkify=True)
    service_count = tables.Column(verbose_name=_('Services'))
    tags = columns.TagColumn(url_name='plugins:netbox_iec62443:fieldbus_list')

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
    interface = tables.Column(verbose_name=_('Interface'), linkify=True)
    ports = columns.ArrayColumn(verbose_name=_('Ports'))
    fieldbus = tables.Column(verbose_name=_('Fieldbus'), linkify=True)
    tags = columns.TagColumn(url_name='plugins:netbox_iec62443:industrialservice_list')

    class Meta(PrimaryModelTable.Meta):
        model = IndustrialService
        fields = (
            'pk', 'id', 'parent', 'protocol', 'role', 'interface', 'ports', 'fieldbus', 'address', 'evidence',
            'description', 'comments', 'tags', 'created', 'last_updated',
        )
        default_columns = ('pk', 'parent', 'protocol', 'role', 'interface', 'ports', 'fieldbus', 'address')
