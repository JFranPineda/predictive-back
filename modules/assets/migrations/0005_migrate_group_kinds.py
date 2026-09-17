"""Turns the hardcoded kind strings into catalogue rows.

Each company gets the six shipped kinds with the point layout the customer's
own reports use — motor on points 1 and 2, driven machine on 3 and 4, three
axes each — and every existing train is pointed at its row.
"""

from django.db import migrations

BUILTIN_KINDS = [
    ("motor_pump", "Motor-Bomba", [("MOTOR", "motor", "driver"), ("BOMBA", "pump", "driven")]),
    ("motor_compressor", "Motor-Compresor",
     [("MOTOR", "motor", "driver"), ("COMPRESOR", "compressor", "driven")]),
    ("motor_turbine", "Motor-Turbina",
     [("MOTOR", "motor", "driver"), ("TURBINA", "turbine", "driven")]),
    ("motor_gearbox", "Motor-Reductor",
     [("MOTOR", "motor", "driver"), ("REDUCTOR", "gearbox", "driven")]),
    ("motor_fan", "Motor-Ventilador",
     [("MOTOR", "motor", "driver"), ("VENTILADOR", "fan", "driven")]),
    ("motor_blower", "Motor-Soplador",
     [("MOTOR", "motor", "driver"), ("SOPLADOR", "blower", "driven")]),
    ("standalone", "Equipo aislado", [("EQUIPO", "other", "driver")]),
]

# Velocity on all three axes, envelope and temperature on the horizontal only:
# the layout of `MPd-AV-N°006-13-EB P-757`.
AXES = ("H", "V", "A")
MAGNITUDES = {"H": ["vel_rms", "env_accel", "temp"], "V": ["vel_rms"], "A": ["vel_rms"]}
SIDES = {0: ("free_end", "coupling_end"), 1: ("coupling_end", "opposite_coupling")}


def seed_kinds(apps, schema_editor):
    Company = apps.get_model("core", "Company")
    AssetGroupKind = apps.get_model("assets", "AssetGroupKind")
    AssetGroupComponent = apps.get_model("assets", "AssetGroupComponent")
    PointTemplate = apps.get_model("assets", "PointTemplate")
    AssetGroup = apps.get_model("assets", "AssetGroup")

    for company in Company.objects.all():
        by_code = {}
        for code, name, components in BUILTIN_KINDS:
            kind = AssetGroupKind.objects.create(
                company=company, code=code, name=name, is_builtin=True,
                translations={"name": {"es": name}},
            )
            by_code[code] = kind
            for index, (label, equipment_type, position) in enumerate(components):
                component = AssetGroupComponent.objects.create(
                    kind=kind, order=index, label=label,
                    equipment_type=equipment_type, position=position,
                )
                first = 1 + index * 2
                for offset in (0, 1):
                    for axis in AXES:
                        PointTemplate.objects.create(
                            kind=kind, component=component, number=first + offset, axis=axis,
                            side=SIDES[index][offset] if index in SIDES else "custom",
                            magnitudes=MAGNITUDES[axis],
                            order=(first + offset) * 10 + AXES.index(axis),
                        )

        fallback = by_code["standalone"]
        for group in AssetGroup.objects.filter(company=company):
            group.kind_ref = by_code.get(group.kind, fallback)
            group.save(update_fields=["kind_ref"])


def drop_kinds(apps, schema_editor):
    apps.get_model("assets", "AssetGroupKind").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("assets", "0004_asset_group_kind_catalogue")]
    operations = [migrations.RunPython(seed_kinds, drop_kinds)]
