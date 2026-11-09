from netbox.plugins import PluginConfig

__version__ = '0.1.0.dev0'


class IEC62443Config(PluginConfig):
    name = 'netbox_iec62443'
    verbose_name = 'IEC 62443'
    description = 'IEC 62443 zones and conduits, Purdue levels and an access map'
    version = __version__
    author = 'Packetflow'
    base_url = 'iec62443'
    min_version = '4.7.0'
    max_version = '4.7.99'
    default_settings = {
        # Create the "Purdue level" custom field on devices and virtual machines after migrate.
        'create_custom_fields': True,
        # The access map lists conduits into zones at this Purdue level or below.
        'access_map_max_level': '2',
    }

    def ready(self):
        super().ready()
        from django.db.models.signals import post_migrate

        from .customfields import ensure_custom_fields
        post_migrate.connect(ensure_custom_fields, sender=self)


config = IEC62443Config
