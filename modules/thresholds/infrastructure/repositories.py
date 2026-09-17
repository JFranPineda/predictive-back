from __future__ import annotations

from decimal import Decimal

from modules.thresholds.domain.entities import (
    Aggregation,
    Band,
    Scope,
    Status,
    StatusKind,
    TechniqueStatusProfile,
    ThresholdSet,
)
from modules.thresholds.infrastructure import models


class DjangoThresholdRepository:
    """Reads every candidate for one magnitude in a single query. The cascade
    stays in the domain — the candidate set is a handful of rows, and running
    the rules in python is what makes them testable and explainable in the UI."""

    def __init__(self, language: str = "es") -> None:
        self._language = language

    def candidates(self, company_id: int, magnitude_code: str) -> tuple[ThresholdSet, ...]:
        rows = (
            models.ThresholdSet.objects.for_company(company_id)
            .filter(magnitude_code=magnitude_code, is_active=True)
            .select_related("standard", "machine_class")
            .prefetch_related("bands__status")
        )
        return tuple(_set_to_domain(row, self._language) for row in rows)


class DjangoStatusProfileRepository:
    def __init__(self, language: str = "es") -> None:
        self._language = language

    def for_technique(self, company_id: int, technique_code: str) -> TechniqueStatusProfile | None:
        profile = (
            models.TechniqueStatusProfile.objects.for_company(company_id)
            .filter(technique__code=technique_code)
            .prefetch_related("options__status")
            .first()
        )
        if profile is None:
            return None
        return TechniqueStatusProfile(
            technique_code=technique_code,
            options=tuple(
                _status_to_domain(option.status, option.display_name, self._language)
                for option in profile.options.all()
            ),
        )


def _status_to_domain(row: models.Status, display_name: str = "", language: str = "es") -> Status:
    return Status(
        code=row.code,
        # The technique-specific override wins over the catalogue name, and the
        # catalogue name is itself translated.
        name=display_name or row.translated("name", language),
        kind=StatusKind(row.kind),
        severity=row.severity,
        color=row.color,
        requires_action=row.requires_action,
        is_terminal=row.is_terminal,
        measurable=row.measurable,
    )


def _set_to_domain(row: models.ThresholdSet, language: str = "es") -> ThresholdSet:
    return ThresholdSet(
        id=row.id,
        magnitude_code=row.magnitude_code,
        unit_code=row.unit_code,
        aggregation=Aggregation(row.aggregation),
        scope=Scope[row.scope.upper()],
        scope_ref_id=_ref(row.scope_ref_id),
        bands=tuple(
            Band(
                status=_status_to_domain(band.status, language=language),
                min_value=_dec(band.min_value),
                max_value=_dec(band.max_value),
            )
            for band in row.bands.all()
        ),
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        is_active=row.is_active,
        standard_code=row.standard.code if row.standard else None,
        machine_class=row.machine_class.code if row.machine_class else None,
        rationale=row.rationale,
        version=row.version,
    )


def _ref(value: str | None) -> int | str | None:
    return int(value) if value and value.isdigit() else value


def _dec(value) -> Decimal | None:
    return Decimal(value) if value is not None else None
