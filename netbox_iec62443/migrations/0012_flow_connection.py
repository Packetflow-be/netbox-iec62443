# Connection models (#11): who opens the connection, and a broker zone for flows through a broker.

import django.contrib.postgres.fields
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("netbox_iec62443", "0011_plugin_settings"),
    ]

    operations = [
        migrations.AddField(
            model_name="flow",
            name="connection",
            field=models.CharField(default="client-server", max_length=20),
        ),
        migrations.AddField(
            model_name="flow",
            name="broker_zone",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="flows_brokered",
                to="netbox_iec62443.zone",
            ),
        ),
        migrations.AddField(
            model_name="flow",
            name="topics",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=255), blank=True, default=list
            ),
        ),
    ]
