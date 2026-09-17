from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from .entities import (
    Evaluation,
    EvaluationContext,
    Scope,
    Standard,
    Status,
    StatusKind,
    TechniqueStatusProfile,
    ThresholdSet,
)
from .errors import OverlappingBands, StandardTechniqueMismatch, StatusNotInProfile


def resolve(
    candidates: Iterable[ThresholdSet],
    context: EvaluationContext,
    moment: date,
) -> ThresholdSet | None:
    """Pick the threshold set that governs this reading.

    A set competes only if its magnitude, aggregation, machine class and
    standard match the equipment. Most specific scope wins; within one scope,
    the newest `valid_from`, then the highest version.

    `env_accel` in Gs peak and `env_accel` in Gs peak-to-peak are different
    criteria and never resolve to each other — the aggregation is part of the
    match, not a display detail.
    """
    matching = [
        candidate
        for candidate in candidates
        if candidate.applies_at(moment)
        and candidate.magnitude_code == context.magnitude_code
        and candidate.aggregation == context.aggregation
        and _scope_matches(candidate, context)
        and candidate.machine_class in (None, context.machine_class)
        and _standard_matches(candidate, context)
    ]
    if not matching:
        return None
    return max(matching, key=lambda c: (c.scope.value, c.valid_from, c.version))


def evaluate(value: Decimal, threshold_set: ThresholdSet | None) -> Evaluation:
    """Reading -> condition status. No set means no verdict, which is honest:
    a value with no criterion behind it must not be reported as normal."""
    if threshold_set is None:
        return Evaluation(status=None, threshold_set_id=None, unmatched=True)
    for band in threshold_set.bands:
        if band.contains(value):
            return Evaluation(status=band.status, threshold_set_id=threshold_set.id)
    # Above every band: the worst declared status. Bands describe the safe
    # region; anything past it is at least as bad as the last one.
    return Evaluation(status=threshold_set.worst_status(), threshold_set_id=threshold_set.id)


def validate_bands(threshold_set: ThresholdSet) -> None:
    """Bands must not overlap. Gaps are allowed (a value in a gap falls through
    to the worst status), overlaps are not — they make the verdict depend on
    ordering, which is how two analysts get two answers from one number."""
    ordered = sorted(
        threshold_set.bands,
        key=lambda b: (b.min_value if b.min_value is not None else Decimal("-Infinity")),
    )
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if previous.max_value is None or (
            current.min_value is not None and current.min_value < previous.max_value
        ):
            raise OverlappingBands(previous.status.code, current.status.code)


def validate_standard_for_magnitude(
    standard: Standard, magnitude_code: str, magnitude_technique: str | None
) -> None:
    """A band set may only cite a standard written for its own technique.

    This is the check that stops NETA MTS — a thermography criterion — from
    being attached to a vibration velocity limit.
    """
    if not standard.covers_technique(magnitude_technique):
        raise StandardTechniqueMismatch(standard.code, magnitude_code, magnitude_technique)


def standards_for_technique(
    standards: Iterable[Standard], technique_code: str
) -> tuple[Standard, ...]:
    """What the UI offers when the user picks a magnitude: only the standards
    that can legitimately judge it."""
    return tuple(s for s in standards if s.covers_technique(technique_code))


def validate_against_profile(
    threshold_set: ThresholdSet, profile: TechniqueStatusProfile
) -> None:
    """A set cannot hand out a status the technique does not have. Without this
    a thermography limit could report PARADA where the profile only offers
    operativo/alarma."""
    for band in threshold_set.bands:
        if not profile.allows(band.status.code) or not band.status.is_condition:
            raise StatusNotInProfile(band.status.code, profile.technique_code)


def declare_availability(
    profile: TechniqueStatusProfile, status_code: str
) -> Status:
    """Availability is chosen by the technician, never derived. It is validated
    against the technique's own vocabulary: no RETIRADO on a vibration route."""
    status = profile.get(status_code)
    if status is None or status.kind is not StatusKind.AVAILABILITY:
        raise StatusNotInProfile(status_code, profile.technique_code)
    return status


def _scope_matches(candidate: ThresholdSet, context: EvaluationContext) -> bool:
    if candidate.scope is Scope.GLOBAL:
        return True
    return candidate.scope_ref_id == context.ref_for(candidate.scope)


def _standard_matches(candidate: ThresholdSet, context: EvaluationContext) -> bool:
    # A set with no standard is a hand-written criterion and always competes;
    # that is what an equipment override is.
    if candidate.standard_code is None:
        return True
    return candidate.standard_code == context.standard_code
