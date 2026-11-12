# System requirements (IEC 62443-3-3) and their status per zone or conduit (#6).

import django.db.models.deletion
import netbox.models.deletion
import taggit.managers
import utilities.json
from django.db import migrations, models


def _primary_fields():
    return [
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
        ("created", models.DateTimeField(auto_now_add=True, null=True)),
        ("last_updated", models.DateTimeField(auto_now=True, null=True)),
        (
            "custom_field_data",
            models.JSONField(blank=True, default=dict, encoder=utilities.json.CustomFieldJSONEncoder),
        ),
        ("description", models.CharField(blank=True, max_length=200)),
        ("comments", models.TextField(blank=True)),
        (
            "owner",
            models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+",
                to="users.owner",
            ),
        ),
        ("tags", taggit.managers.TaggableManager(through="extras.TaggedItem", to="extras.Tag")),
    ]


class Migration(migrations.Migration):

    dependencies = [
        ("extras", "0144_customfield_status"),
        ("netbox_iec62443", "0012_flow_connection"),
        ("tenancy", "0026_consolidate_unique_constraints"),
        ("users", "0016_default_ordering_indexes"),
    ]

    operations = [
        migrations.CreateModel(
            name="SystemRequirement",
            fields=_primary_fields() + [
                ("edition", models.CharField(default="3-3:2013", max_length=20)),
                ("identifier", models.CharField(db_collation="natural_sort", max_length=30)),
                ("foundational_requirement", models.CharField(blank=True, max_length=10)),
                ("security_level", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("wording", models.TextField(blank=True)),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                        related_name="enhancements", to="netbox_iec62443.systemrequirement",
                    ),
                ),
            ],
            options={
                "verbose_name": "system requirement",
                "verbose_name_plural": "system requirements",
                "ordering": ("edition", "identifier"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("edition", "identifier"),
                        name="netbox_iec62443_systemrequirement_unique_edition_identifier",
                        violation_error_message="This requirement already exists in this edition.",
                    ),
                ],
            },
            bases=(netbox.models.deletion.DeleteMixin, models.Model),
        ),
        migrations.CreateModel(
            name="RequirementStatus",
            fields=_primary_fields() + [
                ("status", models.CharField(max_length=20)),
                ("countermeasure", models.TextField(blank=True)),
                ("evidence", models.TextField(blank=True)),
                ("assessed_on", models.DateField(blank=True, null=True)),
                (
                    "assessed_by",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                        related_name="iec62443_requirement_statuses", to="tenancy.contact",
                    ),
                ),
                (
                    "conduit",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                        related_name="requirement_statuses", to="netbox_iec62443.conduit",
                    ),
                ),
                (
                    "requirement",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, related_name="statuses",
                        to="netbox_iec62443.systemrequirement",
                    ),
                ),
                (
                    "risk_assessment",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                        related_name="requirement_statuses", to="netbox_iec62443.riskassessment",
                    ),
                ),
                (
                    "zone",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                        related_name="requirement_statuses", to="netbox_iec62443.zone",
                    ),
                ),
            ],
            options={
                "verbose_name": "requirement status",
                "verbose_name_plural": "requirement statuses",
                "ordering": ("zone", "conduit", "requirement"),
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("zone__isnull", False)),
                        fields=("zone", "requirement"),
                        name="netbox_iec62443_requirementstatus_unique_zone_requirement",
                        violation_error_message="This zone already has a status for this requirement.",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("conduit__isnull", False)),
                        fields=("conduit", "requirement"),
                        name="netbox_iec62443_requirementstatus_unique_conduit_requirement",
                        violation_error_message="This conduit already has a status for this requirement.",
                    ),
                ],
            },
            bases=(netbox.models.deletion.DeleteMixin, models.Model),
        ),
    ]
