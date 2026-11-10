from netbox.search import SearchIndex

from .models import Conduit, Fieldbus, Flow, IndustrialService, Zone


class ZoneIndex(SearchIndex):
    model = Zone
    fields = (
        ('name', 100),
        ('slug', 110),
        ('description', 500),
        ('comments', 5000),
    )
    display_attrs = ('site', 'zone_type', 'purdue_level', 'security_level_target', 'description')


class ConduitIndex(SearchIndex):
    model = Conduit
    fields = (
        ('name', 100),
        ('description', 500),
        ('comments', 5000),
    )
    display_attrs = ('site', 'security_level_target', 'description')


class FlowIndex(SearchIndex):
    model = Flow
    fields = (
        ('name', 100),
        ('description', 500),
        ('evidence', 2000),
        ('comments', 5000),
    )
    display_attrs = ('source_zone', 'destination_zone', 'protocol', 'allowed', 'remote_access', 'conduit')


class FieldbusIndex(SearchIndex):
    model = Fieldbus
    fields = (
        ('name', 100),
        ('description', 500),
        ('comments', 5000),
    )
    display_attrs = ('site', 'zone', 'medium', 'protocol', 'gateway')


class IndustrialServiceIndex(SearchIndex):
    model = IndustrialService
    fields = (
        ('address', 300),
        ('description', 500),
        ('evidence', 2000),
        ('comments', 5000),
    )
    display_attrs = ('device', 'virtual_machine', 'protocol', 'role', 'fieldbus')


indexes = (ZoneIndex, ConduitIndex, FlowIndex, FieldbusIndex, IndustrialServiceIndex)
