"""Which installation a licence covers.

Three identifiers, each stable for a different reason:

- `installation_id`: created once per installation, kept in the control plane
  and in the data volume. Changes only on a reinstall from scratch.
- `pg_system_id`: PostgreSQL's cluster identifier. Changes when the cluster is
  recreated (a restore into a new server, for instance).
- `machine_id`: the server's `/etc/machine-id`. Changes with the machine.

Two of three must match. Moving the application or restoring the database is
normal IT work, and neither should leave a customer without the system; when
two change at once, the licence is reactivated for the new installation.

The machine id is confidential by systemd's own rule, so it never travels
raw: it is hashed with a key of our own, and so is the cluster id.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, fields

REQUIRED_MATCHES = 2
_HASH_KEY = b"predictive-installation-v1"


class InstallationCodeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class InstallationFingerprint:
    installation_id: str = ""
    pg_system_id: str = ""
    machine_id: str = ""

    @property
    def is_bound(self) -> bool:
        return any(getattr(self, f.name) for f in fields(self))

    def matches(self, other: InstallationFingerprint) -> int:
        """Identifiers present on both sides and equal. A missing one never
        matches, not even another missing one."""
        return sum(
            1 for f in fields(self)
            if getattr(self, f.name) and getattr(self, f.name) == getattr(other, f.name)
        )

    def code(self) -> str:
        """What the customer's IT sends us to issue or reactivate a licence."""
        return f"{self.installation_id}:{self.pg_system_id}:{self.machine_id}"

    @classmethod
    def from_code(cls, code: str) -> InstallationFingerprint:
        parts = code.strip().split(":")
        if len(parts) != 3 or not any(parts):
            raise InstallationCodeError("el código de instalación es <instalación>:<postgresql>:<máquina>")
        return cls(*parts)


def installation_fingerprint(
    installation_id: str | None, pg_system_id: str | int | None, machine_id: str | None
) -> InstallationFingerprint:
    return InstallationFingerprint(
        installation_id=(installation_id or "").strip(),
        pg_system_id=_hashed("pg", pg_system_id),
        machine_id=_hashed("machine", machine_id),
    )


def belongs_to(licensed: InstallationFingerprint, observed: InstallationFingerprint) -> bool:
    """An unbound licence (hosted, or issued before installations) belongs
    anywhere."""
    return not licensed.is_bound or licensed.matches(observed) >= REQUIRED_MATCHES


def _hashed(kind: str, value: str | int | None) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        return ""
    return hmac.new(_HASH_KEY, f"{kind}|{text}".encode(), hashlib.sha256).hexdigest()[:32]
