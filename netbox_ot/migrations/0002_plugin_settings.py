# Plugin settings changed in the GUI (#9): one row, not change-logged, so netbox-branching does not branch it.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("netbox_ot", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PluginSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("branching_enabled", models.BooleanField(default=False)),
                ("default_branch", models.CharField(blank=True, max_length=100)),
                ("protect_main", models.BooleanField(default=False)),
                ("last_updated", models.DateTimeField(auto_now=True, null=True)),
                ("updated_by", models.CharField(blank=True, max_length=150)),
            ],
            options={
                "verbose_name": "plugin settings",
                "verbose_name_plural": "plugin settings",
            },
        ),
    ]
