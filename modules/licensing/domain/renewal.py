"""Renewing a licence (v4 Phase 3).

Each period paid is one licence we sign. It reaches the customer's server by
one of two roads: a `.lic` file their administrator uploads, which works on a
network with no way out, or the daily check against our renewal service.

What leaves their network is the renewal request and nothing else: customer,
licence, installation, program version and two counts. Never maintenance
data. It is plain text on purpose, so their IT can read it before sending it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from modules.licensing.domain.installation import InstallationFingerprint, belongs_to
from modules.licensing.domain.license import License


class RenewalRejectedError(Exception):
    """A renewal file that does not apply here; the message says why, in the
    customer's words."""


@dataclass(frozen=True, slots=True)
class RenewalRequest:
    tenant: str
    # Empty on a new installation: its first licence is the one it asks for
    # (v4 Phase 6, P6-c).
    license_id: str
    valid_until: date | None
    installation: str
    version: str
    equipment: int
    users: int

    def text(self) -> str:
        return "\n".join((
            "PREDICTIVE · solicitud de licencia",
            f"cliente: {self.tenant}",
            f"licencia: {self.license_id or 'ninguna (primera licencia)'}",
            f"vence: {self.valid_until.isoformat() if self.valid_until else '—'}",
            f"instalación: {self.installation}",
            f"versión: {self.version}",
            f"equipos: {self.equipment}",
            f"usuarios: {self.users}",
        ))

    def payload(self) -> dict[str, Any]:
        """The same fields, for the online service."""
        return {
            "tenant": self.tenant,
            "license": self.license_id,
            "until": self.valid_until.isoformat() if self.valid_until else None,
            "installation": self.installation,
            "version": self.version,
            "equipment": self.equipment,
            "users": self.users,
        }


def check_renewal(
    new: License, *, tenant_code: str, current: License | None, observed: InstallationFingerprint
) -> None:
    """The signature is already checked; this is whether the licence applies
    here. The same term is allowed: that is a reactivation for a new
    installation. A shorter one is not: loading last quarter's file by
    mistake must never cut the term in force."""
    if new.tenant_code != tenant_code:
        raise RenewalRejectedError(
            f"Esta licencia es para el cliente «{new.tenant_code}», no para «{tenant_code}»."
        )
    if not belongs_to(new.installation, observed):
        raise RenewalRejectedError(
            "Esta licencia es de otra instalación. Envía a Industrie Ampel la solicitud de licencia "
            "de este servidor y te enviaremos la que le corresponde."
        )
    if current is not None and new.valid_until < current.valid_until:
        raise RenewalRejectedError(
            f"Esta licencia vence el {new.valid_until.isoformat()}, antes que la vigente "
            f"({current.valid_until.isoformat()}): no se carga una licencia más corta."
        )


def renewal_answer(answer: object) -> tuple[str, str]:
    """What the online service said: ("renewed", token), ("pending", "") or
    ("error", ""). Anything unexpected is an error, never a licence."""
    if not isinstance(answer, dict):
        return "error", ""
    status = answer.get("status")
    licence = answer.get("licence")
    if status == "renewed" and isinstance(licence, str) and licence.strip():
        return "renewed", licence.strip()
    if status == "pending":
        return "pending", ""
    return "error", ""
