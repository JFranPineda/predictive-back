"""How tight a laser alignment must be, and whether one reading passes.

The customer's SKF report judges the *absolute* value of each of the four
numbers against a tolerance that depends on running speed: a slow ID fan
tolerates what a 3600 RPM pump cannot. The table below is a generic,
widely-used starting point (tighter as RPM climbs) — Q10 in V3-17 asks the
customer for 1A-MIG's own SKF chart, and it replaces this one the day it
arrives, without anyone touching a line of code: `AlignmentTolerance` rows
are data, tiered by RPM and overridable per train.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise

# (rpm_ceiling exclusive, parallel mm, angular mm/100mm). The last tier has no
# ceiling. Illustrative defaults — see the module docstring.
DEFAULT_TIERS: tuple[tuple[int | None, Decimal, Decimal], ...] = (
    (1000, Decimal("0.10"), Decimal("0.10")),
    (2000, Decimal("0.07"), Decimal("0.07")),
    (4000, Decimal("0.05"), Decimal("0.05")),
    (None, Decimal("0.03"), Decimal("0.03")),
)


@dataclass(frozen=True, slots=True)
class Tolerance:
    parallel_mm: Decimal
    angular_mm_per_100mm: Decimal


@dataclass(frozen=True, slots=True)
class AxisValues:
    """The four numbers a laser tool reports for one phase (before/after)."""

    angular_h: Decimal | None
    parallel_h: Decimal | None
    angular_v: Decimal | None
    parallel_v: Decimal | None


@dataclass(frozen=True, slots=True)
class AxisVerdict:
    angular_h: bool | None
    parallel_h: bool | None
    angular_v: bool | None
    parallel_v: bool | None

    @property
    def all_ok(self) -> bool:
        checks = (self.angular_h, self.parallel_h, self.angular_v, self.parallel_v)
        return all(check is not False for check in checks) and any(check is not None for check in checks)


Tier = tuple[int | None, Decimal, Decimal]


def tier_for(rpm: Decimal | float | int, tiers: Sequence[Tier]) -> Tolerance | None:
    """The first tier whose ceiling is above this speed; past the last, the
    last (the strictest), which is the safe direction to guess wrong."""
    ordered = sorted(tiers, key=lambda tier: (tier[0] is None, tier[0] or 0))
    if not ordered:
        return None
    value = float(rpm)
    for ceiling, parallel, angular in ordered:
        if ceiling is None or value < ceiling:
            return Tolerance(parallel, angular)
    return Tolerance(*ordered[-1][1:])


def default_tolerance_for(rpm: Decimal | float | int) -> Tolerance:
    """The illustrative tier that covers this speed."""
    return tier_for(rpm, DEFAULT_TIERS)  # type: ignore[return-value]


class InvalidTiersError(ValueError):
    pass


def check_tiers(tiers: Sequence[Tier]) -> None:
    """A norma's RPM scale must read top to bottom: ceilings that climb, only
    the last one open, and tolerances above zero."""
    if not tiers:
        raise InvalidTiersError("La escala necesita al menos un tramo de RPM")
    ceilings = [tier[0] for tier in tiers]
    if None in ceilings[:-1]:
        raise InvalidTiersError("Solo el último tramo puede no tener techo de RPM")
    closed = [c for c in ceilings if c is not None]
    if any(b <= a for a, b in pairwise(closed)):
        raise InvalidTiersError("Los techos de RPM deben ir de menor a mayor")
    if any(parallel <= 0 or angular <= 0 for _, parallel, angular in tiers):
        raise InvalidTiersError("Las tolerancias deben ser mayores que cero")


def within(value: Decimal | None, tolerance: Decimal) -> bool | None:
    """A value is judged by its magnitude, sign and all: −0.40 mm against a
    0.10 mm tolerance fails exactly like 0.40 mm."""
    if value is None:
        return None
    return abs(value) <= tolerance


def evaluate(values: AxisValues, tolerance: Tolerance) -> AxisVerdict:
    return AxisVerdict(
        angular_h=within(values.angular_h, tolerance.angular_mm_per_100mm),
        parallel_h=within(values.parallel_h, tolerance.parallel_mm),
        angular_v=within(values.angular_v, tolerance.angular_mm_per_100mm),
        parallel_v=within(values.parallel_v, tolerance.parallel_mm),
    )


# ---------------------------------------------------------------- states (Q10)
#
# A norma's RPM tier is not only a ✓/✗ line: it names the equipment's state
# for each range of values — "up to 0.05 mm Aceptable, up to 0.10 mm Alarma,
# above that Parada". Each band is "up to this limit, this state"; one band
# without limits is what everything above the last limit is. A value is ✓
# while it falls inside a band with limits.


@dataclass(frozen=True, slots=True)
class Band:
    status_code: str | None
    status_name: str
    color: str
    severity: int
    parallel_mm: Decimal | None
    angular_mm_per_100mm: Decimal | None

    @property
    def bounded(self) -> bool:
        return self.parallel_mm is not None and self.angular_mm_per_100mm is not None


LIMIT_OF = {"parallel": "parallel_mm", "angular": "angular_mm_per_100mm"}


def kind_of(axis: str) -> str:
    """`angular_h` is judged against the angular limit, `parallel_v` the parallel one."""
    return axis.split("_")[0]


def state_of(value: Decimal | None, kind: str, bands: Sequence[Band]) -> Band | None:
    """The band a value falls in: the first limit its magnitude does not pass,
    or the open band above them all. None when there is no value, or no band
    covers it."""
    if value is None:
        return None
    limit = LIMIT_OF[kind]
    for band in sorted((b for b in bands if b.bounded), key=lambda b: getattr(b, limit)):
        if abs(value) <= getattr(band, limit):
            return band
    return next((band for band in bands if not band.bounded), None)


def worst(states: Sequence[Band | None]) -> Band | None:
    found = [state for state in states if state is not None and state.status_code]
    return max(found, key=lambda band: band.severity, default=None)


def acceptance(bands: Sequence[Band]) -> Tolerance | None:
    """The ✓ line of a tier: the widest limits that still have a band."""
    bounded = [band for band in bands if band.bounded]
    if not bounded:
        return None
    return Tolerance(
        max(band.parallel_mm for band in bounded),  # type: ignore[type-var]
        max(band.angular_mm_per_100mm for band in bounded),  # type: ignore[type-var]
    )


def check_bands(bands: Sequence[Band]) -> None:
    """One tier's bands: at least one with limits, limits above zero that
    climb with each band, and at most one open band."""
    bounded = [band for band in bands if band.bounded]
    if not bounded:
        raise InvalidTiersError("Cada tramo de RPM necesita al menos un límite")
    if len(bands) - len(bounded) > 1:
        raise InvalidTiersError("Solo puede haber un estado «por encima de todos los límites» por tramo")
    if any(band.parallel_mm <= 0 or band.angular_mm_per_100mm <= 0 for band in bounded):  # type: ignore[operator]
        raise InvalidTiersError("Las tolerancias deben ser mayores que cero")
    # In limit order, whatever order they were typed in: both limits climb.
    ordered = sorted(bounded, key=lambda band: band.parallel_mm)  # type: ignore[arg-type,return-value]
    for kind in LIMIT_OF.values():
        limits = [getattr(band, kind) for band in ordered]
        if any(b <= a for a, b in pairwise(limits)):
            raise InvalidTiersError("Dentro de un tramo, cada límite debe ser mayor que el anterior")
    codes = [band.status_code for band in bands if band.status_code]
    if len(codes) != len(set(codes)):
        raise InvalidTiersError("Un estado aparece una sola vez por tramo")


# The norma the illustrative chart becomes (Q10): its scale is editable from
# Normas, and a client can add its own next to it.
SKF_NORMA_CODE = "skf_alignment"
SKF_NORMA_NAME = "SKF · Tolerancias de alineamiento por RPM"
SKF_NORMA_SOURCE = "Tabla de tolerancias por velocidad, formato SKF (valores de partida editables)"
