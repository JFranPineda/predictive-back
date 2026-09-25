"""The two families the customer sells (V3-19).

MPd Predictivo monitors condition over time; END (ensayos no destructivos)
inspects the integrity of a part. Airborne ultrasound (dB, friction and leaks)
is MPd; contact UT (mm) is END — the same word, two services. Maintenance and
lubrication come from the customer's RGP and are not services anybody orders.
"""

from __future__ import annotations

MPD = "mpd"
NDT = "ndt"
INTERNAL = "internal"
FAMILIES = (MPD, NDT, INTERNAL)

_DEFAULT_FAMILY = {
    "vibration": MPD,
    "ultrasound": MPD,
    "thermography": MPD,
    "oil_analysis": MPD,
    "insulating_oil": MPD,
    "alignment": MPD,
    "topography": MPD,
    "ndt_thickness": NDT,
    "ndt_penetrant": NDT,
    "ndt_magnetic": NDT,
    "ndt_rollers": NDT,
    "maintenance": INTERNAL,
    "lubrication": INTERNAL,
}


def family_for(technique_code: str) -> str:
    return _DEFAULT_FAMILY.get(technique_code, MPD)


def is_offered(family: str) -> bool:
    """Whether a service order can be opened for it."""
    return family != INTERNAL
