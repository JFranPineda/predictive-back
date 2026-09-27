"""Q16: OBSERVACIÓN ships with the catalogue, for every company.

A machine built outside the standard has no shutdown limit the standard would
recognise, so its norma judges it "en observación" instead. The state was born
in IPSA's import; here it reaches the companies that already existed.
"""

from django.db import migrations
from django.db.models import F

from modules.thresholds.domain.defaults import OBSERVATION

# Where it sits in each technique's list: right after operativo.
AFTER = "operational"


def add_observation(apps, schema_editor):
    Status = apps.get_model("thresholds", "Status")
    Option = apps.get_model("thresholds", "TechniqueStatusOption")
    alias = schema_editor.connection.alias

    for company_id in (
        Status.objects.using(alias).values_list("company_id", flat=True).distinct()
    ):
        status, _ = Status.objects.using(alias).get_or_create(
            company_id=company_id,
            code=OBSERVATION.code,
            defaults={
                "name": OBSERVATION.name,
                "kind": "condition",
                "severity": OBSERVATION.severity,
                "color": OBSERVATION.color,
                "translations": {"name": {"es": "Observación", "en": "Under observation"}},
            },
        )
        # Only the techniques that already grade a condition offer it.
        for option in Option.objects.using(alias).filter(
            profile__company_id=company_id, status__code=AFTER
        ):
            if Option.objects.using(alias).filter(
                profile_id=option.profile_id, status=status
            ).exists():
                continue
            Option.objects.using(alias).filter(
                profile_id=option.profile_id, order__gt=option.order
            ).update(order=F("order") + 1)
            Option.objects.using(alias).create(
                profile_id=option.profile_id, status=status, order=option.order + 1
            )


class Migration(migrations.Migration):

    dependencies = [
        ("thresholds", "0003_machine_class_power_range"),
    ]

    operations = [
        migrations.RunPython(add_observation, migrations.RunPython.noop),
    ]
