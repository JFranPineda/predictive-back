"""Wall thickness is its own service, not a reading of the ultrasound round.

An ultrasound round is airborne ultrasound, reported in decibels: friction,
leaks, bearing condition. A thickness sweep with a contact probe is a
non-destructive test — the IPSA report in `docs/v2` names it so, "Ensayos No
Destructivos, Ultrasonido Convencional (UT)" — reported in millimetres.

Keeping both under one technique made the plant view print a thickness in the
ultrasound tab, and worse, let a thickness alarm colour an area whose printed
number was a healthy dB level: the number stopped explaining the colour.
"""

from django.db import migrations

ULTRASOUND_HEADLINE = "us_db"
THICKNESS = "thickness_mm"
NDT = "ndt_thickness"


def split_services(apps, schema_editor):
    alias = schema_editor.connection.alias
    Technique = apps.get_model("measurements", "Technique")
    Magnitude = apps.get_model("measurements", "Magnitude")
    Profile = apps.get_model("thresholds", "TechniqueStatusProfile")
    Option = apps.get_model("thresholds", "TechniqueStatusOption")

    ndt, _ = Technique.objects.using(alias).update_or_create(
        code=NDT,
        defaults={
            "name": "END · Espesores UT",
            # Same instrument family as the ultrasound module; a different
            # service, reported in a different unit.
            "module_code": "ultrasound",
            "headline_magnitude": THICKNESS,
            "translations": {
                "name": {"es": "END · Espesores UT", "en": "NDT · UT thickness"},
            },
        },
    )
    Technique.objects.using(alias).filter(code="ultrasound").update(
        headline_magnitude=ULTRASOUND_HEADLINE
    )
    Magnitude.objects.using(alias).filter(code=THICKNESS).update(technique=ndt)

    # A visit of the new service offers the same availability states as the
    # ultrasound one; without a profile its form would offer none.
    source = Profile.objects.using(alias).filter(technique__code="ultrasound").first()
    if source and not Profile.objects.using(alias).filter(technique=ndt).exists():
        clone = Profile.objects.using(alias).create(company_id=source.company_id, technique=ndt)
        for option in Option.objects.using(alias).filter(profile=source):
            Option.objects.using(alias).create(
                profile=clone, status_id=option.status_id,
                order=option.order, display_name=option.display_name,
            )


class Migration(migrations.Migration):
    dependencies = [
        ("measurements", "0006_technique_headline"),
        ("thresholds", "0003_machine_class_power_range"),
    ]

    operations = [migrations.RunPython(split_services, migrations.RunPython.noop)]
