"""Grading readings again when the norma of their report changes (Q9)."""

from __future__ import annotations

from modules.thresholds.application.evaluation import context_for


def regrade(readings, standard=None) -> int:
    """Grades these readings again, with the report's norma when it has one.

    Called when an order's norma changes: the report must say what the
    readings are under the criterion it now cites, not the one it had.
    """
    from modules.thresholds.domain.services import evaluate, resolve
    from modules.thresholds.infrastructure.models import Status
    from modules.thresholds.infrastructure.repositories import DjangoThresholdRepository

    repository = DjangoThresholdRepository()
    candidates: dict[tuple[int, str], list] = {}
    statuses: dict[tuple[int, str], object] = {}
    changed = 0
    for reading in readings:
        if reading.value is None:
            continue
        key = (reading.company_id, reading.magnitude.code)
        if key not in candidates:
            candidates[key] = repository.candidates(*key)
        context = context_for(reading.point.equipment, reading.magnitude.code, reading.aggregation,
                              reading.point_id, standard=standard)
        verdict = evaluate(reading.value, resolve(candidates[key], context, reading.taken_at.date()))
        code = verdict.status.code if verdict.status else None
        if code and (reading.company_id, code) not in statuses:
            statuses[(reading.company_id, code)] = Status.objects.filter(
                company_id=reading.company_id, code=code
            ).first()
        status = statuses.get((reading.company_id, code)) if code else None
        if reading.condition_status_id != getattr(status, "id", None) or (
            reading.threshold_set_id != verdict.threshold_set_id
        ):
            reading.condition_status = status
            reading.threshold_set_id = verdict.threshold_set_id
            reading.save(update_fields=["condition_status", "threshold_set"])
            changed += 1
    return changed
