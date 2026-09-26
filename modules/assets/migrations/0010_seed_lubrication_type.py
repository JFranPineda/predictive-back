"""Every existing motor gets grease, every existing gearbox gets oil — the
same rule V3-29 gives a new equipment, applied once to what AMBEV already has.

Anything the customer didn't name (soplador included) is left blank: nothing
here is confident enough to guess it.
"""

from django.db import migrations

from modules.assets.domain.lubrication import default_lubrication_for


def seed(apps, schema_editor):
    alias = schema_editor.connection.alias
    Equipment = apps.get_model("assets", "Equipment")

    for equipment_type in ("compressor", "pump", "gearbox", "motor"):
        Equipment.objects.using(alias).filter(
            equipment_type=equipment_type, lubrication_type=""
        ).update(lubrication_type=default_lubrication_for(equipment_type))


class Migration(migrations.Migration):
    dependencies = [
        ("assets", "0009_equipment_lubrication_type"),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
