"""Topografía's own technique row, family mpd, gated on its plan (V3-18).

A fresh database builds it in the seed already pointed here; on AMBEV the
technique never existed at all, unlike alignment which just had the wrong
module_code.
"""

from django.db import migrations


def seed(apps, schema_editor):
    alias = schema_editor.connection.alias
    Technique = apps.get_model("measurements", "Technique")

    Technique.objects.using(alias).update_or_create(
        code="topography",
        defaults={
            "name": "Topografía",
            "module_code": "topography",
            "family": "mpd",
            "close_requirement": "plan_required",
            "translations": {"name": {"es": "Topografía", "en": "Topography"}},
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("topography", "0001_initial"),
        ("measurements", "0014_technique_close_requirement"),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
