"""The order the record of values prints its tables in.

The customer's sheet reads velocity first, then acceleration, then the
acceleration envelope, then temperature (V3-10). Sorting the blocks by their
internal code did the opposite — "env_accel" < "temp" < "vel_rms" put the
headline magnitude last.
"""

from __future__ import annotations

UNLISTED = 900

DEFAULT_DISPLAY_ORDER: dict[str, int] = {
    "vel_rms": 10,
    "accel_rms": 20,
    "env_accel": 30,
    "ir_tmax": 39,
    "temp": 40,
    "delta_temp": 41,
    "delta_temp_ambient": 42,
    "us_db": 50,
    "thickness_mm": 60,
    "viscosity_40": 70,
    "water_ppm": 71,
    "dielectric_kv": 80,
}


def display_order_for(code: str) -> int:
    return DEFAULT_DISPLAY_ORDER.get(code, UNLISTED)


def block_sort_key(display_order: int | None, block_key: str) -> tuple[int, str]:
    """By the configured order; the code only breaks ties, so two aggregations
    of one magnitude (Gs peak and peak-to-peak) keep a stable order."""
    return (UNLISTED if display_order is None else display_order, block_key)
