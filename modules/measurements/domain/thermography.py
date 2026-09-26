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


def thermogram_values(tmax: Decimal | None, delta: Decimal | None) -> list[tuple[str, Decimal | None]]:
    """What one thermogram records: its Tmax, and the ΔT the technician read.

    ΔT is typed as it is, in °C (Q8): the client reads it off the camera's own
    analysis. It was computed here from a reference temperature, which asked
    the technician for a number the client does not use.
    """
    values: list[tuple[str, Decimal | None]] = [(IR_TMAX, tmax)]
    if delta is not None:
        values.append((DELTA_TEMP, delta))
    return values
