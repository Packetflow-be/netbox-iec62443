from netbox.search import SearchIndex

from .models import Conduit, Zone


class ZoneIndex(SearchIndex):
    model = Zone
    fields = (
        ('name', 100),
        ('slug', 110),
        ('description', 500),
        ('comments', 5000),
    )
    display_attrs = ('site', 'purdue_level', 'security_level_target', 'description')


class ConduitIndex(SearchIndex):
    model = Conduit
    fields = (
        ('name', 100),
        ('via', 300),
        ('protocols', 400),
        ('description', 500),
        ('evidence', 2000),
        ('comments', 5000),
    )
    display_attrs = ('source_zone', 'destination_zone', 'allowed', 'remote_access', 'via')


indexes = (ZoneIndex, ConduitIndex)
