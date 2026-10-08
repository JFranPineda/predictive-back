"""0004 offered OBSERVACIÓN to every service that had Operativo, which caught
maintenance and lubrication: they declare whether a machine works and grade
nothing, so a state "to watch" means nothing there."""

from django.db import migrations

NOT_GRADED = ("maintenance", "lubrication")


def drop(apps, schema_editor):
    Option = apps.get_model("thresholds", "TechniqueStatusOption")
    Option.objects.using(schema_editor.connection.alias).filter(
        status__code="observation", profile__technique__code__in=NOT_GRADED
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("thresholds", "0004_observation_status"),
    ]

    operations = [
        migrations.RunPython(drop, migrations.RunPython.noop),
    ]
