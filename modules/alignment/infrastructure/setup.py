"""What installing `alignment` gives each company: the SKF norma with its RPM
scale and its states (Q10). Idempotent: an upgrade runs it again, and a scale
somebody edited is left as it is."""

from __future__ import annotations

# How alignment names the plant's condition states, unless the company
# already renamed them.
STATE_NAMES = {"operational": "Aceptable", "alarm": "Fuera de tolerancia", "shutdown": "Crítico"}
# The SKF chart's states: within the tier's tolerance Aceptable, above it
# Fuera de tolerancia. More bands are added from Normas.
WITHIN, BEYOND = "operational", "alarm"


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
    from modules.thresholds.models import Status, ThresholdStandard

    technique = Technique.objects.filter(code="alignment").first()
    for company in Company.objects.all():
        norma, _ = ThresholdStandard.objects.get_or_create(
            company=company,
            code=SKF_NORMA_CODE,
            defaults={
                "name": SKF_NORMA_NAME,
                "source": SKF_NORMA_SOURCE,
                "is_builtin": True,
                "translations": {"name": {"es": SKF_NORMA_NAME}},
            },
        )
        if technique is not None:
            norma.techniques.add(technique)
            _profile(company, technique)
        AlignmentTolerance.objects.filter(
            company=company, asset_group__isnull=True, standard__isnull=True
        ).update(standard=norma)

        statuses = {row.code: row for row in Status.objects.for_company(company.id).filter(kind="condition")}
        within, beyond = statuses.get(WITHIN), statuses.get(BEYOND)
        tiers = AlignmentTolerance.objects.filter(standard=norma, asset_group__isnull=True)
        if not tiers.exists():
            rows = []
            for ceiling, parallel, angular in DEFAULT_TIERS:
                rows.append(
                    AlignmentTolerance(
                        company=company,
                        standard=norma,
                        rpm_ceiling=ceiling,
                        status=within,
                        parallel_mm=parallel,
                        angular_mm_per_100mm=angular,
                    )
                )
                if beyond is not None:
                    rows.append(
                        AlignmentTolerance(
                            company=company, standard=norma, rpm_ceiling=ceiling, status=beyond
                        )
                    )
            AlignmentTolerance.objects.bulk_create(rows)
        elif within is not None and not tiers.filter(status__isnull=False).exists():
            # The chart from before states: its ✓ line becomes Aceptable, and
            # above it Fuera de tolerancia, so the SKF norma reads as a scale.
            ceilings = set(tiers.values_list("rpm_ceiling", flat=True))
            tiers.update(status=within)
            if beyond is not None:
                AlignmentTolerance.objects.bulk_create(
                    [
                        AlignmentTolerance(
                            company=company, standard=norma, rpm_ceiling=ceiling, status=beyond
                        )
                        for ceiling in ceilings
                    ]
                )


def _profile(company, technique) -> None:
    from modules.thresholds.models import Status, TechniqueStatusOption, TechniqueStatusProfile

    profile, _ = TechniqueStatusProfile.objects.get_or_create(company=company, technique=technique)
    if profile.options.exists():
        return
    statuses = {row.code: row for row in Status.objects.for_company(company.id)}
    for order, (code, name) in enumerate(STATE_NAMES.items()):
        if code in statuses:
            TechniqueStatusOption.objects.create(
                profile=profile, status=statuses[code], order=order, display_name=name
            )
