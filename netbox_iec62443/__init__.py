from netbox.plugins import PluginConfig

__version__ = '0.2.0'


class IEC62443Config(PluginConfig):
    name = 'netbox_iec62443'
    verbose_name = 'IEC 62443'
    description = 'IEC 62443 zones, conduits and flows, Purdue levels, an access map and a zone register'
    version = __version__
    author = 'Packetflow'
    base_url = 'iec62443'
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
        super().ready()
        from django.db.models.signals import post_migrate

        from .customfields import ensure_custom_fields
        from .upgrade import after_upgrade
        post_migrate.connect(ensure_custom_fields, sender=self)
        post_migrate.connect(after_upgrade, sender=self)


config = IEC62443Config
