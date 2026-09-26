"""Alignment's own technique row, pointed at this module, and the SKF tier
chart as the global (asset-group-less) default (V3-17).

A fresh database has no `alignment` technique yet — the seed builds it
already pointed here. Here we only fix an existing one: on AMBEV it was
created before this module existed, filed under `operating_data`
(`SUMMARY.md`, "la técnica alignment existe... sin magnitud titular").
"""

from django.db import migrations

from modules.alignment.domain.tolerances import DEFAULT_TIERS


def seed(apps, schema_editor):
    alias = schema_editor.connection.alias
    Technique = apps.get_model("measurements", "Technique")
    Company = apps.get_model("core", "Company")
    Tolerance = apps.get_model("alignment", "AlignmentTolerance")

    Technique.objects.using(alias).filter(code="alignment").update(module_code="alignment")

    for company in Company.objects.using(alias).all():
        if Tolerance.objects.using(alias).filter(company=company, asset_group__isnull=True).exists():
            continue
        for ceiling, parallel, angular in DEFAULT_TIERS:
            Tolerance.objects.using(alias).create(
                company=company, asset_group=None, rpm_ceiling=ceiling,
                parallel_mm=parallel, angular_mm_per_100mm=angular,
            )


class Migration(migrations.Migration):
    dependencies = [
        ("alignment", "0001_initial"),
        ("measurements", "0013_thermography_ir_tmax"),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
