from netbox.plugins import PluginConfig

__version__ = '0.4.1'


class NetBoxOTConfig(PluginConfig):
    name = 'netbox_ot'
    verbose_name = 'OT'
    description = (
        'OT asset and security register: IEC 62443 zones, conduits and flows, Purdue levels, an access map, '
        'a zone register and lifecycle checks'
    )
    version = __version__
    author = 'Packetflow'
    base_url = 'ot'
    # Tested in CI on 4.7.0, the newest 4.7 release and NetBox's development branch for the next release (weekly)
    min_version = '4.7.0'
    max_version = '4.8.99'
    default_settings = {
        # Create the "Purdue level" custom field on devices and virtual machines after migrate.
        'create_custom_fields': True,
        # The access map lists flows into zones at this Purdue level or below.
        'access_map_max_level': '2',
        # A flow not seen for this many days needs attention.
        'stale_after_days': 90,
    }

    def ready(self):
        from django.conf import settings
        from django.core.exceptions import ImproperlyConfigured

        if 'netbox_iec62443' in settings.PLUGINS:
            # netbox-ot takes the old plugin's tables over on migrate (adopt.py); both at once would break both
            raise ImproperlyConfigured(
                'netbox-ot replaces netbox-iec62443: remove netbox_iec62443 from PLUGINS (and its PLUGINS_CONFIG '
                'entry; move the settings to netbox_ot), then run migrate.'
            )
        super().ready()
        from django.db.models.signals import post_migrate

        from .customfields import ensure_custom_fields
        from .upgrade import after_upgrade
        post_migrate.connect(ensure_custom_fields, sender=self)
        post_migrate.connect(after_upgrade, sender=self)


config = NetBoxOTConfig
