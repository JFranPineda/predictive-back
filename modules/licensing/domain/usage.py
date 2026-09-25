"""How much of the plan a customer uses, and whether one more fits (V3-36).

A plan sells a ceiling. Growth stops at it — creating or reactivating a
machine — but the work never does: readings on existing machines are always
accepted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

WARN_RATIO = 0.9

_NAMES: dict[str, tuple[str, str]] = {
    "equipment": ("equipo", "equipos"),
    "plants": ("planta", "plantas"),
    "users": ("usuario", "usuarios"),
    "external_users": ("usuario externo", "usuarios externos"),
}


@dataclass(frozen=True, slots=True)
class Usage:
    resource: str
    used: int
    allowed: int | None  # None: the plan sets no ceiling

    @property
    def near_limit(self) -> bool:
        return self.allowed is not None and self.used >= math.ceil(self.allowed * WARN_RATIO)

    def fits(self, adding: int = 1) -> bool:
        return self.allowed is None or self.used + adding <= self.allowed


def limit_message(usage: Usage, adding: int = 1, provider: str = "1A-MIG") -> str:
    singular, plural = _NAMES.get(usage.resource, (usage.resource, usage.resource))
    if adding > 1:
        room = max((usage.allowed or 0) - usage.used, 0)
        return (f"Esta carga traería {adding} {plural} y el plan solo admite {room} más. "
                f"Contacta con {provider} para ampliarlo.")
    unit = singular if usage.allowed == 1 else plural
    return (f"Tu plan permite {usage.allowed} {unit} y ya tienes {usage.used}. "
            f"Contacta con {provider} para ampliarlo.")
