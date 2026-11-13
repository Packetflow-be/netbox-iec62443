# Likelihood and impact of the unmitigated and the residual risk of a risk assessment: where they sit on the
# organisation's risk matrix. Optional, so existing assessments stay as they are.

import django.core.validators
from django.db import migrations, models


def _field(name):
    return models.PositiveSmallIntegerField(
        blank=True, null=True, validators=[django.core.validators.MinValueValidator(1)], verbose_name=name,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("netbox_ot", "0004_system_requirements"),
    ]

    operations = [
        migrations.AddField("riskassessment", "unmitigated_likelihood", _field("unmitigated likelihood")),
        migrations.AddField("riskassessment", "unmitigated_impact", _field("unmitigated impact")),
        migrations.AddField("riskassessment", "residual_likelihood", _field("residual likelihood")),
        migrations.AddField("riskassessment", "residual_impact", _field("residual impact")),
    ]
