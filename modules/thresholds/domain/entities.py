"""Thresholds, statuses and standards (T12).

Three rules the source Excels broke and this module keeps:

1. A status is either *condition* (derived from a measured value) or
   *availability* (declared, explaining why there is no value). They may be
   shown in one list per technique, but they are never computed the same way.
2. Which statuses exist depends on the technique: a maintenance visit has no
   ALARMA, a vibration route has no RETIRADO.
3. Limits come from a standard (ISO 10816-3, ISO 20816-3, Technical
   Associates...) chosen per equipment, and an equipment-level override always
   wins over it — with author, date and rationale attached.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import IntEnum, StrEnum


class Scope(IntEnum):
    """Resolution order: the most specific active set wins."""

    GLOBAL = 10
    EQUIPMENT_TYPE = 20
    ASSET_GROUP_KIND = 30
    EQUIPMENT = 40
    POINT = 50


class Aggregation(StrEnum):
    RMS = "rms"
    PEAK = "peak"
    PEAK_TO_PEAK = "peak_to_peak"
    AVG = "avg"
    MAX = "max"


class StatusKind(StrEnum):
    CONDITION = "condition"
    AVAILABILITY = "availability"


@dataclass(frozen=True, slots=True)
class Status:
    code: str
    name: str
    kind: StatusKind
    severity: int
    color: str = "#888888"
    requires_action: bool = False
    is_terminal: bool = False
    # Availability only: whether a reading can be taken while in this state.
    measurable: bool = True

    @property
    def is_condition(self) -> bool:
        return self.kind is StatusKind.CONDITION


@dataclass(frozen=True, slots=True)
class TechniqueStatusProfile:
    """The status vocabulary of one technique.

    vibration/ultrasound -> apagado, operativo, alarma, parada
    thermography         -> operativo, alarma, parada, apagado
    maintenance          -> apagado, retirado, fuera de servicio, operativo
    """

    technique_code: str
    options: tuple[Status, ...]

    @property
    def condition_options(self) -> tuple[Status, ...]:
        return tuple(o for o in self.options if o.kind is StatusKind.CONDITION)

    @property
    def availability_options(self) -> tuple[Status, ...]:
        return tuple(o for o in self.options if o.kind is StatusKind.AVAILABILITY)

    def allows(self, status_code: str) -> bool:
        return any(o.code == status_code for o in self.options)

    def get(self, status_code: str) -> Status | None:
        return next((o for o in self.options if o.code == status_code), None)

    def worst_condition(self) -> Status | None:
        conditions = self.condition_options
        return max(conditions, key=lambda s: s.severity) if conditions else None


@dataclass(frozen=True, slots=True)
class MachineClass:
    """ISO 10816-3 splits machines by power and mounting (I..IV); other
    standards use their own groups. The class is part of the standard, not a
    free-text field on the equipment."""

    code: str
    name: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class Standard:
    code: str
    name: str
    source: str = ""
    machine_classes: tuple[MachineClass, ...] = ()
    is_builtin: bool = False

    def has_class(self, code: str | None) -> bool:
        return code is None or any(c.code == code for c in self.machine_classes)


@dataclass(frozen=True, slots=True)
class Band:
    """Half-open band [min, max). `None` means unbounded on that side."""

    status: Status
    min_value: Decimal | None
    max_value: Decimal | None

    def contains(self, value: Decimal) -> bool:
        if self.min_value is not None and value < self.min_value:
            return False
        if self.max_value is not None and value >= self.max_value:
            return False
        return True


@dataclass(frozen=True, slots=True)
class ThresholdSet:
    id: int
    magnitude_code: str
    unit_code: str
    aggregation: Aggregation
    scope: Scope
    scope_ref_id: int | str | None
    bands: tuple[Band, ...]
    valid_from: date
    valid_to: date | None = None
    is_active: bool = True
    standard_code: str | None = None
    machine_class: str | None = None
    rationale: str = ""
    version: int = 1

    def applies_at(self, moment: date) -> bool:
        if not self.is_active or moment < self.valid_from:
            return False
        return self.valid_to is None or moment <= self.valid_to

    def worst_status(self) -> Status:
        return max((b.status for b in self.bands), key=lambda s: s.severity)


@dataclass(frozen=True, slots=True)
class EvaluationContext:
    """Everything the cascade needs to know about what is being measured."""

    magnitude_code: str
    aggregation: Aggregation
    point_id: int | None = None
    equipment_id: int | None = None
    equipment_type: str | None = None
    asset_group_kind: str | None = None
    machine_class: str | None = None
    # The standard assigned to this equipment. Sets from any other standard are
    # out of play; custom sets (no standard) still compete.
    standard_code: str | None = None

    def ref_for(self, scope: Scope) -> int | str | None:
        return {
            Scope.POINT: self.point_id,
            Scope.EQUIPMENT: self.equipment_id,
            Scope.EQUIPMENT_TYPE: self.equipment_type,
            Scope.ASSET_GROUP_KIND: self.asset_group_kind,
            Scope.GLOBAL: None,
        }[scope]


@dataclass(frozen=True, slots=True)
class Evaluation:
    status: Status | None
    threshold_set_id: int | None
    unmatched: bool = field(default=False)
