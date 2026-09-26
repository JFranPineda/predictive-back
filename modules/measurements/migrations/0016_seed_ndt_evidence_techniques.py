"""Tintes penetrantes and partículas magnéticas: no magnitude, no reading
plan, just photos and a conclusion before the visit can close (V3-20).

Their family (`ndt`) was already anticipated in `domain/families.py` when
V3-19 split MPd from END; this is what actually creates the rows.
"""

from django.db import migrations

TECHNIQUES = (
    ("ndt_penetrant", "Tintes penetrantes", "Dye penetrant testing"),
    ("ndt_magnetic", "Partículas magnéticas", "Magnetic particle testing"),
)


def seed(apps, schema_editor):
    alias = schema_editor.connection.alias
    Technique = apps.get_model("measurements", "Technique")

    for code, name_es, name_en in TECHNIQUES:
        Technique.objects.using(alias).update_or_create(
            code=code,
            defaults={
                "name": name_es,
                "module_code": "measurements",
                "family": "ndt",
                "evidence_only": True,
                "translations": {"name": {"es": name_es, "en": name_en}},
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("measurements", "0015_technique_evidence_only"),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
