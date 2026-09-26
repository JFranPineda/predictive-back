"""The RPM chart becomes a norma's scale (Q10): each company gets the SKF
alignment norma, and its global tiers are that norma's."""

from django.db import migrations

from modules.alignment.domain.tolerances import SKF_NORMA_CODE, SKF_NORMA_NAME, SKF_NORMA_SOURCE


def attach(apps, schema_editor):
    alias = schema_editor.connection.alias
    Company = apps.get_model("core", "Company")
    Standard = apps.get_model("thresholds", "ThresholdStandard")
    Technique = apps.get_model("measurements", "Technique")
    Tolerance = apps.get_model("alignment", "AlignmentTolerance")
    technique = Technique.objects.using(alias).filter(code="alignment").first()

    for company in Company.objects.using(alias).all():
        tiers = Tolerance.objects.using(alias).filter(company=company, asset_group__isnull=True)
        if not tiers.exists():
            continue
        norma, _ = Standard.objects.using(alias).get_or_create(
            company=company, code=SKF_NORMA_CODE,
            defaults={"name": SKF_NORMA_NAME, "source": SKF_NORMA_SOURCE, "is_builtin": True,
                      "translations": {"name": {"es": SKF_NORMA_NAME}}},
        )
        if technique is not None:
            norma.techniques.add(technique)
        tiers.filter(standard__isnull=True).update(standard=norma)


class Migration(migrations.Migration):
    dependencies = [
        ("alignment", "0003_tolerance_standard"),
        ("measurements", "0016_seed_ndt_evidence_techniques"),
    ]

    operations = [migrations.RunPython(attach, migrations.RunPython.noop)]
