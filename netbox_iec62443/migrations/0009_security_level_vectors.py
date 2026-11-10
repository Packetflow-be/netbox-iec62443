"""
The single SL-T integer becomes a vector over the seven foundational requirements: SL-T n is SL-T {n n n n n n n}.
"""
from django.db import migrations


def forward(apps, schema_editor):
    for model in ('Zone', 'Conduit'):
        Model = apps.get_model('netbox_iec62443', model)
        for pk, level in Model.objects.filter(security_level_target__isnull=False).values_list(
                'pk', 'security_level_target'):
            Model.objects.filter(pk=pk).update(sl_target=[level] * 7)


def backward(apps, schema_editor):
    for model in ('Zone', 'Conduit'):
        Model = apps.get_model('netbox_iec62443', model)
        for pk, levels in Model.objects.filter(sl_target__isnull=False).values_list('pk', 'sl_target'):
            Model.objects.filter(pk=pk).update(security_level_target=max(levels))


class Migration(migrations.Migration):

    dependencies = [
        ('netbox_iec62443', '0008_audit_layer'),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
