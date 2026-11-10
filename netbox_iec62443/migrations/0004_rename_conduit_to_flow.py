import django.db.models.deletion
from django.db import migrations, models

KEEP = {'netbox_iec62443_conduit_unique_zones_name'}  # replaced by name in 0005


def _flow_name(name):
    if name in KEEP:
        return name
    return name.replace('netbox_iec62443_conduit', 'netbox_iec62443_flow').replace(
        'netbox_iec62443_cond_', 'netbox_iec62443_flow_')


def rename_table_objects(apps, schema_editor):
    """
    PostgreSQL keeps index, constraint and sequence names when a table is renamed. Give the old conduit table's
    objects flow names, so the new conduit table (0005) can use its own.
    """
    if schema_editor.connection.vendor != 'postgresql':
        return
    qn = schema_editor.quote_name
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT conname FROM pg_constraint WHERE conrelid = 'netbox_iec62443_flow'::regclass")
        for (name,) in cursor.fetchall():
            if _flow_name(name) != name:
                cursor.execute(f'ALTER TABLE netbox_iec62443_flow RENAME CONSTRAINT {qn(name)} TO {qn(_flow_name(name))}')
        cursor.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'netbox_iec62443_flow'")
        for (name,) in cursor.fetchall():
            if _flow_name(name) != name:
                cursor.execute(f'ALTER INDEX {qn(name)} RENAME TO {qn(_flow_name(name))}')
        cursor.execute("SELECT pg_get_serial_sequence('netbox_iec62443_flow', 'id')")
        sequence = cursor.fetchone()[0]
        if sequence and 'netbox_iec62443_conduit' in sequence:
            cursor.execute(f'ALTER SEQUENCE {sequence} RENAME TO netbox_iec62443_flow_id_seq')


class Migration(migrations.Migration):
    """
    The old Conduit was a directed zone pair with a verdict: what this plugin now calls a Flow. Rename it in place,
    so ids, tags, journal entries, custom field data, permissions and the change log stay attached; 0005 then adds
    the new IEC 62443-3-2 Conduit model.
    """

    dependencies = [
        ('netbox_iec62443', '0003_protect_zone_conduits'),
    ]

    operations = [
        migrations.RenameModel('Conduit', 'Flow'),
        migrations.RunPython(rename_table_objects, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='flow',
            name='source_zone',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='flows_out',
                                    to='netbox_iec62443.zone', verbose_name='source zone'),
        ),
        migrations.AlterField(
            model_name='flow',
            name='destination_zone',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='flows_in',
                                    to='netbox_iec62443.zone', verbose_name='destination zone'),
        ),
    ]
