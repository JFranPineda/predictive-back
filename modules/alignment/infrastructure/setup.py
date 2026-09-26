"""What installing `alignment` gives each company: the SKF norma with its RPM
scale (Q10). Idempotent: an upgrade runs it again, and a scale somebody
edited is left as it is."""

from __future__ import annotations


def install() -> None:
    from modules.alignment.domain.tolerances import (
        DEFAULT_TIERS,
        SKF_NORMA_CODE,
        SKF_NORMA_NAME,
        SKF_NORMA_SOURCE,
    )
    from modules.alignment.infrastructure.models import AlignmentTolerance
    from modules.core.models import Company
    from modules.measurements.models import Technique
    from modules.thresholds.models import ThresholdStandard

    technique = Technique.objects.filter(code="alignment").first()
    for company in Company.objects.all():
        norma, _ = ThresholdStandard.objects.get_or_create(
            company=company, code=SKF_NORMA_CODE,
            defaults={"name": SKF_NORMA_NAME, "source": SKF_NORMA_SOURCE, "is_builtin": True,
                      "translations": {"name": {"es": SKF_NORMA_NAME}}},
        )
        if technique is not None:
            norma.techniques.add(technique)
        AlignmentTolerance.objects.filter(
            company=company, asset_group__isnull=True, standard__isnull=True
        ).update(standard=norma)
        if not AlignmentTolerance.objects.filter(standard=norma).exists():
            AlignmentTolerance.objects.bulk_create([
                AlignmentTolerance(company=company, standard=norma, rpm_ceiling=ceiling,
                                   parallel_mm=parallel, angular_mm_per_100mm=angular)
                for ceiling, parallel, angular in DEFAULT_TIERS
            ])
