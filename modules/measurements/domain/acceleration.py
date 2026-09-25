"""Global acceleration in g RMS (V3-11).

The customer's sheet lists it between velocity and envelope ("Aceleración gEs
RMS"), which also settles the pending question of peak or RMS. It is read per
axis like velocity, and only where a kind's template asks for it. No standard
is loaded for it: its readings are kept without a verdict rather than judged
against invented limits.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MagnitudeSpec:
    code: str
    technique: str
    name_es: str
    name_en: str
    unit: str
    aggregation: str
    decimals: int
    per_axis: bool
    higher_is_worse: bool
    template_only: bool


ACCELERATION = MagnitudeSpec(
    code="accel_rms", technique="vibration", name_es="Aceleración", name_en="Acceleration",
    unit="g", aggregation="rms", decimals=2, per_axis=True, higher_is_worse=True,
    template_only=True,
)
