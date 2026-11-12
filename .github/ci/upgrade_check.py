"""
CI only, run with `manage.py nbshell -c "exec(open(...).read())"`: what an installation of the plugin holds, to
compare before and after the upgrade from netbox-iec62443 0.2.0 (the `upgrade` job in ci.yml).

UPGRADE_STEP=before: on netbox-iec62443, add a tag, a journal entry, a permission and a custom field value next
to the demo plant, then write the snapshot to UPGRADE_SNAPSHOT. UPGRADE_STEP=after: on netbox-ot, take the
same snapshot and fail when it differs.
"""
import json
import os
import sys

from django.apps import apps

from core.models import ObjectType
from dcim.models import Device
from extras.models import CustomField, JournalEntry, Tag
from users.models import ObjectPermission

step = os.environ['UPGRADE_STEP']
app_label, prefix = ('netbox_iec62443', 'iec62443_') if step == 'before' else ('netbox_ot', 'ot_')
purdue = f'{prefix}purdue_level'
Zone = apps.get_model(app_label, 'Zone')
zone_type = ObjectType.objects.get_for_model(Zone)

if step == 'before':
    zone = Zone.objects.order_by('pk').first()
    zone.tags.add(Tag.objects.create(name='upgrade-check', slug='upgrade-check'))
    JournalEntry.objects.create(assigned_object=zone, comments='before the rename')
    permission = ObjectPermission.objects.create(name='zone viewers', actions=['view'])
    permission.object_types.add(zone_type)
    device = Device.objects.order_by('pk').first()
    device.custom_field_data[purdue] = '1'
    device.save()

snapshot = {
    'objects': {model.__name__: model.objects.count() for model in apps.get_app_config(app_label).get_models()},
    'zone_type': zone_type.pk,
    'permission': ObjectPermission.objects.filter(name='zone viewers', object_types=zone_type).exists(),
    'journal': JournalEntry.objects.filter(assigned_object_type=zone_type).count(),
    'tagged': Zone.objects.filter(tags__slug='upgrade-check').count(),
    'custom_fields': sorted(
        name.removeprefix(prefix) for name in CustomField.objects.filter(name__startswith=prefix)
        .values_list('name', flat=True)
    ),
    'purdue_values': Device.objects.filter(**{f'custom_field_data__{purdue}__isnull': False}).count(),
}
print(json.dumps(snapshot, indent=2, sort_keys=True))

if step == 'before':
    with open(os.environ['UPGRADE_SNAPSHOT'], 'w') as f:
        json.dump(snapshot, f)
else:
    with open(os.environ['UPGRADE_SNAPSHOT']) as f:
        before = json.load(f)
    if before != snapshot:
        print('The upgrade changed the data; before:', json.dumps(before, indent=2, sort_keys=True))
        sys.exit(1)
    if not snapshot['objects']['Zone']:
        print('No zones: the demo plant was not created')
        sys.exit(1)
    print('Upgrade from netbox-iec62443 kept everything')
