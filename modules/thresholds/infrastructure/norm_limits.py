"""Loads the norms' published limits into a customer's database (P6-e).

Only what is missing: a norm set the customer already has, edited or not, is
left as it is, and so is every set of their own.
"""

from __future__ import annotations

from modules.thresholds.domain.norm_limits import NORM_LIMITS, NORM_VALID_FROM


class MissingCatalogueError(LookupError):
    pass


def load_norm_limits(company) -> int:
    from modules.thresholds.infrastructure.models import (
        MachineClass,
        Status,
        ThresholdBand,
        ThresholdSet,
        ThresholdStandard,
    )

    statuses = {row.code: row for row in Status.objects.filter(company=company)}
    created = 0
    for limit in NORM_LIMITS:
        standard = ThresholdStandard.objects.filter(company=company, code=limit.standard).first()
        missing = [code for code, _, _ in limit.bands() if code not in statuses]
        if standard is None or missing:
            raise MissingCatalogueError(
                f"falta el catálogo base en {company.code} ({limit.standard}, {', '.join(missing)}): "
                "corre antes `catalog base`"
            )
        machine_class = (
            MachineClass.objects.filter(standard=standard, code=limit.machine_class).first()
            if limit.machine_class else None
        )
        if ThresholdSet.objects.filter(
            company=company, standard=standard, machine_class=machine_class, scope="global",
            scope_ref_id=None, magnitude_code=limit.magnitude, aggregation=limit.aggregation,
        ).exists():
            continue
        threshold = ThresholdSet.objects.create(
            company=company, standard=standard, machine_class=machine_class, scope="global",
            scope_ref_id=None, magnitude_code=limit.magnitude, unit_code=limit.unit,
            aggregation=limit.aggregation, valid_from=NORM_VALID_FROM, rationale=limit.rationale,
        )
        ThresholdBand.objects.bulk_create([
            ThresholdBand(
                threshold_set=threshold, status=statuses[code], min_value=low, max_value=high, order=order
            )
            for order, (code, low, high) in enumerate(limit.bands())
        ])
        created += 1
    return created
