"""What each equipment type is lubricated with, by default (V3-29).

Only the types the customer named get a default; the rest — soplador
included, which the customer said can go either way — start unset and force
an explicit choice.
"""

from __future__ import annotations

LUBRICATION_TYPES = (("oil", "Aceite"), ("grease", "Grasa"), ("none", "Ninguno"))

_DEFAULT_BY_EQUIPMENT_TYPE = {
    "compressor": "oil",
    "pump": "oil",
    "gearbox": "oil",
    "motor": "grease",
}


def default_lubrication_for(equipment_type: str) -> str:
    return _DEFAULT_BY_EQUIPMENT_TYPE.get(equipment_type, "")
