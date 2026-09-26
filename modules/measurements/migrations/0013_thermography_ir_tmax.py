"""Tmax gets its own magnitude, and ΔT becomes the semáforo's titular (V3-16).

A fresh database has no catalogue yet — the seed builds `ir_tmax` itself, from
the same spec this migration reads. On AMBEV, `temp` is the collector's
bearing reading, not a thermogram's Tmax (`SUMMARY.md`, "las 20 088 lecturas
de termografía no vienen de termogramas"); switching the technique's headline
to `delta_temp` is what makes the plant traffic light print the worst ΔT
instead of a temperature that was never a thermogram's.
"""

from django.db import migrations

from modules.measurements.domain.magnitude_order import display_order_for
from modules.measurements.domain.thermography import IR_TMAX_SPEC as SPEC


def add_ir_tmax(apps, schema_editor):
    alias = schema_editor.connection.alias
    Technique = apps.get_model("measurements", "Technique")
    Unit = apps.get_model("measurements", "Unit")
    Magnitude = apps.get_model("measurements", "Magnitude")

    technique = Technique.objects.using(alias).filter(code=SPEC.technique).first()
    unit = Unit.objects.using(alias).filter(code=SPEC.unit).first()
    if technique is None or unit is None:
        return
    Magnitude.objects.using(alias).update_or_create(
        code=SPEC.code,
        defaults={
            "technique": technique, "name": SPEC.name_es, "default_unit": unit,
            "default_aggregation": SPEC.aggregation, "decimals": SPEC.decimals,
            "higher_is_worse": SPEC.higher_is_worse, "per_axis": SPEC.per_axis,
            "short_code": SPEC.short_code, "display_order": display_order_for(SPEC.code),
            "translations": {"name": {"es": SPEC.name_es, "en": SPEC.name_en}},
        },
    )
    technique.headline_magnitude = "delta_temp"
    technique.save(using=alias, update_fields=["headline_magnitude"])


class Migration(migrations.Migration):
    dependencies = [
        ("measurements", "0012_reading_image"),
    ]

    operations = [
        migrations.RunPython(add_ir_tmax, migrations.RunPython.noop),
    ]
