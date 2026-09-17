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


class Mounting(StrEnum):
    """ISO 10816-3 grades the same machine differently depending on what it
    stands on: a flexible foundation absorbs vibration the rigid one passes to
    the structure."""

    RIGID = "rigid"
    FLEXIBLE = "flexible"
    ANY = "any"


@dataclass(frozen=True, slots=True)
class MachineClass:
    """ISO 10816-3 splits machines by power and mounting; other standards use
    their own groups. The class belongs to the standard, not to the equipment.

    `power_min_kw` / `power_max_kw` are what let the system pick the class on
    its own: the field crew types the motor's rated power, and the limits that
    apply follow from the standard instead of from somebody remembering which
    group a 45 kW pump belongs to.
    """

    code: str
    name: str
    description: str = ""
    power_min_kw: float | None = None
    power_max_kw: float | None = None
    mounting: Mounting = Mounting.ANY

    def covers(self, power_kw: float | None, mounting: str | None = None) -> bool:
        if self.mounting is not Mounting.ANY and mounting and mounting != self.mounting.value:
            return False
        if self.power_min_kw is None and self.power_max_kw is None:
            return False
        if power_kw is None:
            return False
        # Ranges are half-open upwards: 15 kW belongs to the 15-300 group, and
        # 300 kW to the one above, which is how the tables are written.
        if self.power_min_kw is not None and power_kw < self.power_min_kw:
            return False
        if self.power_max_kw is not None and power_kw >= self.power_max_kw:
            return False
        return True


@dataclass(frozen=True, slots=True)
class Standard:
    """A standard belongs to the technique it was written for.

    ISO 10816-3 judges vibration velocity; NETA MTS judges thermographic ΔT;
    ISO 14830 judges lubricant condition. Leaving that unsaid let a
    thermography standard be attached to a vibration limit — nothing in the
    system objected, and the mistake only showed up in a report.

    An empty tuple means "any technique", which is what a company's own
    in-house criterion usually is.
    """

    code: str
    name: str
    source: str = ""
    machine_classes: tuple[MachineClass, ...] = ()
    techniques: tuple[str, ...] = ()
    is_builtin: bool = False

    def has_class(self, code: str | None) -> bool:
        return code is None or any(c.code == code for c in self.machine_classes)

    def classify(self, power_kw: float | None, mounting: str | None = None) -> MachineClass | None:
        """The class this standard would put a machine of that power in."""
        for machine_class in self.machine_classes:
            if machine_class.covers(power_kw, mounting):
                return machine_class
        return None

    def covers_technique(self, technique_code: str | None) -> bool:
        if not self.techniques:
            return True
        return technique_code is not None and technique_code in self.techniques


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
    # Nameplate power and mounting, so the machine class can be worked out
    # rather than remembered.
    rated_power_kw: float | None = None
    mounting: str | None = None
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
