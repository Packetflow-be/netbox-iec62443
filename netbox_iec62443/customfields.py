"""
The plugin keeps a Purdue level on devices and virtual machines as a NetBox custom field
(no change to core tables). It is created after `migrate` when missing and never overwritten,
so an admin may relabel or regroup it. Disable with PLUGINS_CONFIG create_custom_fields=False.
"""
import logging

from django.conf import settings

from .choices import PurdueLevelChoices

logger = logging.getLogger('netbox.plugins.netbox_iec62443')

PURDUE_CF_NAME = 'iec62443_purdue_level'
PURDUE_CHOICE_SET_NAME = 'IEC 62443 Purdue levels'
PURDUE_CF_MODELS = (('dcim', 'device'), ('virtualization', 'virtualmachine'))


def ensure_custom_fields(sender=None, **kwargs):
    if not settings.PLUGINS_CONFIG.get('netbox_iec62443', {}).get('create_custom_fields', True):
        return
    from django.apps import apps

    from core.models import ObjectType
    from extras.choices import CustomFieldTypeChoices
    from extras.models import CustomField, CustomFieldChoiceSet

    choice_set, created = CustomFieldChoiceSet.objects.get_or_create(
        name=PURDUE_CHOICE_SET_NAME,
        defaults={
            'description': 'Purdue reference model levels (netbox-iec62443)',
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
            'description': 'Purdue reference model level of this asset (netbox-iec62443)',
            'choice_set': choice_set,
        },
    )
    if created:
        cf.object_types.set([
            ObjectType.objects.get_for_model(apps.get_model(app_label, model))
            for app_label, model in PURDUE_CF_MODELS
        ])
        logger.info('Created custom field %s', PURDUE_CF_NAME)


def get_purdue_level(obj):
    """The asset's Purdue level value ('' when unset)."""
    return (getattr(obj, 'custom_field_data', None) or {}).get(PURDUE_CF_NAME) or ''
