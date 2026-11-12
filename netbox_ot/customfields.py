"""
The plugin keeps a Purdue level on devices and virtual machines, a security level capability (SL-C) on
devices and device types, and a firmware version on devices and modules, as NetBox custom fields (no change to
core tables). They are created after `migrate` when missing and never overwritten, so an admin may relabel or
regroup them. Disable with PLUGINS_CONFIG create_custom_fields=False.
"""
import logging

from django.conf import settings

from .choices import PurdueLevelChoices

logger = logging.getLogger('netbox.plugins.netbox_ot')

PURDUE_CF_NAME = 'ot_purdue_level'
PURDUE_CHOICE_SET_NAME = 'IEC 62443 Purdue levels'
PURDUE_CF_MODELS = (('dcim', 'device'), ('virtualization', 'virtualmachine'))
SLC_CF_NAME = 'ot_sl_capability'
SLC_CF_MODELS = (('dcim', 'device'), ('dcim', 'devicetype'))
SLC_REGEX = r'^[0-4]( ?, ?[0-4]){6}$|^[0-4]$'
FIRMWARE_CF_NAME = 'ot_firmware_version'
FIRMWARE_CF_MODELS = (('dcim', 'device'), ('dcim', 'module'))


def ensure_custom_fields(sender=None, **kwargs):
    if not settings.PLUGINS_CONFIG.get('netbox_ot', {}).get('create_custom_fields', True):
        return
    from django.apps import apps

    from core.models import ObjectType
    from extras.choices import CustomFieldTypeChoices
    from extras.models import CustomField, CustomFieldChoiceSet

    choice_set, created = CustomFieldChoiceSet.objects.get_or_create(
        name=PURDUE_CHOICE_SET_NAME,
        defaults={
            'description': 'Purdue reference model levels (netbox-ot)',
            'extra_choices': [[value, str(label)] for value, label in PurdueLevelChoices.CHOICES],
            'choice_colors': dict(PurdueLevelChoices.colors),
        },
    )
    if created:
        logger.info('Created custom field choice set %s', PURDUE_CHOICE_SET_NAME)

    cf, created = CustomField.objects.get_or_create(
        name=PURDUE_CF_NAME,
        defaults={
            'type': CustomFieldTypeChoices.TYPE_SELECT,
            'label': 'Purdue level',
            'group_name': 'IEC 62443',
            'description': 'Purdue reference model level of this asset (netbox-ot)',
            'choice_set': choice_set,
        },
    )
    if created:
        cf.object_types.set([
            ObjectType.objects.get_for_model(apps.get_model(app_label, model))
            for app_label, model in PURDUE_CF_MODELS
        ])
        logger.info('Created custom field %s', PURDUE_CF_NAME)

    cf, created = CustomField.objects.get_or_create(
        name=SLC_CF_NAME,
        defaults={
            'type': CustomFieldTypeChoices.TYPE_TEXT,
            'label': 'SL-C',
            'group_name': 'IEC 62443',
            'description': 'Security level capability per FR (IAC,UC,SI,DC,RDF,TRE,RA), e.g. "2,2,2,1,2,1,1", or one '
                           'level for all. On a device it overrides its device type (netbox-ot)',
            'validation_regex': SLC_REGEX,
        },
    )
    if created:
        cf.object_types.set([
            ObjectType.objects.get_for_model(apps.get_model(app_label, model))
            for app_label, model in SLC_CF_MODELS
        ])
        logger.info('Created custom field %s', SLC_CF_NAME)

    cf, created = CustomField.objects.get_or_create(
        name=FIRMWARE_CF_NAME,
        defaults={
            'type': CustomFieldTypeChoices.TYPE_TEXT,
            'label': 'Firmware version',
            'group_name': 'Lifecycle',
            'description': 'Firmware or software version running on this device or module, e.g. "V2.9.4" for a '
                           'PLC CPU module (netbox-ot)',
        },
    )
    if created:
        cf.object_types.set([
            ObjectType.objects.get_for_model(apps.get_model(app_label, model))
            for app_label, model in FIRMWARE_CF_MODELS
        ])
        logger.info('Created custom field %s', FIRMWARE_CF_NAME)


def get_purdue_level(obj):
    """The asset's Purdue level value ('' when unset)."""
    return (getattr(obj, 'custom_field_data', None) or {}).get(PURDUE_CF_NAME) or ''


def get_firmware_version(obj):
    """The firmware version recorded on a device or module ('' when unset)."""
    return (getattr(obj, 'custom_field_data', None) or {}).get(FIRMWARE_CF_NAME) or ''


def get_sl_capability(device):
    """The device's SL-C vector: its own custom field, else its device type's, else None."""
    from django.core.exceptions import ValidationError

    from . import sl

    for obj in (device, getattr(device, 'device_type', None)):
        value = (getattr(obj, 'custom_field_data', None) or {}).get(SLC_CF_NAME)
        if value:
            try:
                return sl.parse(value)
            except ValidationError:
                return None
    return None
