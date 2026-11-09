import django_tables2 as tables
from django.utils.translation import gettext_lazy as _

from netbox.tables import PrimaryModelTable, columns
from tenancy.tables import TenancyColumnsMixin

from .models import Conduit, Zone

__all__ = ('ConduitTable', 'ZoneTable')


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
