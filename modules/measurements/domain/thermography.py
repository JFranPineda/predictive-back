"""What a thermogram contributes to the record: Tmax and a ΔT (V3-16).

The IPSA sheet has no value table — it is images, one per element observed,
each carrying its own Tmax and its scale. Contact and infrared measure
different things (the bearing's inside against the surface the camera sees),
so Tmax gets its own magnitude, `ir_tmax`, distinct from `temp` (the collector
reading vibration rounds already take on the same bearing).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

IR_TMAX = "ir_tmax"
DELTA_TEMP = "delta_temp"


@dataclass(frozen=True, slots=True)
class MagnitudeSpec:
    code: str
    technique: str
    name_es: str
    name_en: str
    unit: str
    aggregation: str
    decimals: int
    higher_is_worse: bool
    per_axis: bool
    short_code: str


IR_TMAX_SPEC = MagnitudeSpec(
    code=IR_TMAX, technique="thermography", name_es="Temperatura IR máxima",
    name_en="Maximum IR temperature", unit="°C", aggregation="max", decimals=1,
    higher_is_worse=True, per_axis=False, short_code="IR {n}",
)


def delta_of(tmax: Decimal, reference: Decimal) -> Decimal:
    """ΔT is signed the way the sheet reads it: how much hotter than the
    reference the element is."""
    return tmax - reference
