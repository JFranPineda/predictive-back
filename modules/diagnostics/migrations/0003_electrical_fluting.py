"""Fluting joins ultrasound's catalogue, and bearing_friction's own name
starts saying "rascado" too — the client's two names for one dB signature
(V3-22).

FaultMode is per-company, so every existing company gets both: fresh ones
from `seed_demo` already read the same `ALL_FAULTS` this migration does.
"""

from django.db import migrations

from modules.diagnostics.domain.catalogue import ALL_FAULTS

NEW_OR_RENAMED = ("bearing_friction", "electrical_fluting")


def seed(apps, schema_editor):
    alias = schema_editor.connection.alias
    Company = apps.get_model("core", "Company")
    FaultMode = apps.get_model("diagnostics", "FaultMode")

    definitions = {d.code: d for d in ALL_FAULTS if d.code in NEW_OR_RENAMED}
    for company in Company.objects.using(alias).all():
        for code, definition in definitions.items():
            FaultMode.objects.using(alias).update_or_create(
                company=company, code=code,
                defaults={
                    "name": definition.name_es,
                    "technique_code": definition.technique,
                    "typical_signature": definition.signature,
                    "iso_reference": definition.reference,
                    "translations": {
                        "name": {"es": definition.name_es, "en": definition.name_en}
                    },
                },
            )


class Migration(migrations.Migration):
    dependencies = [
        ("diagnostics", "0002_faultmode_is_active_alter_faultmode_iso_reference"),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
