"""The limits the norms publish, as data we load on purpose (decision P6-e).

A new customer starts with no limits. These are the zones printed in ISO
10816-1 and -3 per machine class, and NETA MTS's two thermographic
comparisons; `manage.py catalog limits` loads them into any customer's
database, on premise or in the cloud, and leaves the customer's own sets
alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from modules.thresholds.domain.defaults import (
    ISO_BANDS_BY_CLASS,
    NETA_DELTA_AMBIENT,
    NETA_DELTA_SIMILAR,
    STANDARDS,
)

# A norm does not start the day it is loaded: it grades the years of history
# a customer imports too.
NORM_VALID_FROM = date(2000, 1, 1)

_ISO_CLASSED = ("iso_10816_1", "iso_10816_3")


@dataclass(frozen=True, slots=True)
class NormLimit:
    standard: str
    machine_class: str | None
    magnitude: str
    aggregation: str
    unit: str
    low: Decimal
    high: Decimal
    rationale: str

    def bands(self) -> tuple[tuple[str, Decimal | None, Decimal | None], ...]:
        """Below `low` operational, up to `high` alarm, above it shutdown."""
        return (
            ("operational", None, self.low),
            ("alarm", self.low, self.high),
            ("shutdown", self.high, None),
        )


def _iso() -> list[NormLimit]:
    limits = []
    for standard in STANDARDS:
        if standard.code not in _ISO_CLASSED:
            continue
        for machine_class in standard.machine_classes:
            bounds = ISO_BANDS_BY_CLASS.get(machine_class.code)
            if bounds is None:
                continue
            limits.append(NormLimit(
                standard=standard.code, machine_class=machine_class.code,
                magnitude="vel_rms", aggregation="rms", unit="mm/s",
                low=Decimal(bounds[0]), high=Decimal(bounds[1]),
                rationale=f"{standard.name} · {machine_class.name}",
            ))
    return limits


def _neta() -> list[NormLimit]:
    return [
        NormLimit(
            standard="neta_mts", machine_class=None, magnitude=magnitude, aggregation="max",
            unit="°C", low=Decimal(bounds[0]), high=Decimal(bounds[1]), rationale=rationale,
        )
        for magnitude, bounds, rationale in (
            ("delta_temp", NETA_DELTA_SIMILAR,
             "ΔT contra un componente similar con igual carga (NETA MTS)"),
            ("delta_temp_ambient", NETA_DELTA_AMBIENT,
             "ΔT sobre la temperatura ambiente (NETA MTS)"),
        )
    ]


NORM_LIMITS: tuple[NormLimit, ...] = (*_iso(), *_neta())


def norm_limit(standard: str, machine_class: str | None) -> NormLimit | None:
    return next(
        (limit for limit in NORM_LIMITS
         if limit.standard == standard and limit.machine_class == machine_class),
        None,
    )
