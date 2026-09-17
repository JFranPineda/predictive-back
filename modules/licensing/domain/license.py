"""Licensing.

The commercial shape this has to support: the customer keeps their data in
their own database, on their own premises, and the application that gives that
data any meaning — schema, rules, screens, reports — runs on ours. The licence
is what ties the two together.

Be honest about what a key does and does not do:

- It **does** stop our hosted application from serving a tenant whose contract
  ended, and it does it at a single chokepoint instead of in a hundred views.
- It **does not** encrypt the customer's database. They own those rows and can
  read them with `psql` any day. What they cannot take is the system: an empty
  schema without the application is a filing cabinet with no index.
- Verification runs on **our** servers, never on customer hardware, so a shared
  secret (HMAC) is enough. Asymmetric signing only buys something when the
  verifier is in hostile hands — here it would be ceremony.

Expiry degrades before it blocks: read-only during the grace period, then
refusal. Cutting a maintenance team off mid-round because an invoice is three
days late makes an enemy, not a payment.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum

TOKEN_VERSION = 1


class LicenseError(Exception):
    pass


class MalformedToken(LicenseError):
    pass


class BadSignature(LicenseError):
    pass


class LicenseStatus(StrEnum):
    ACTIVE = "active"
    GRACE = "grace"
    EXPIRED = "expired"
    REVOKED = "revoked"
    SUSPENDED = "suspended"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class LicenseLimits:
    max_plants: int | None = None
    max_equipment: int | None = None
    max_users: int | None = None
    max_external_users: int | None = None

    def limit_for(self, resource: str) -> int | None:
        return getattr(self, f"max_{resource}", None)


@dataclass(frozen=True, slots=True)
class License:
    tenant_code: str
    plan: str
    issued_at: date
    valid_until: date
    license_id: str
    grace_days: int = 15
    limits: LicenseLimits = field(default_factory=LicenseLimits)
    modules: tuple[str, ...] = ()
    # Ties the key to one customer database. Re-pointing the deployment at a
    # copy of the data does not silently reuse the licence.
    database_fingerprint: str = ""

    def allows_module(self, code: str) -> bool:
        return not self.modules or code in self.modules

    def grace_until(self) -> date:
        return date.fromordinal(self.valid_until.toordinal() + self.grace_days)


@dataclass(frozen=True, slots=True)
class LicenseVerdict:
    status: LicenseStatus
    read_only: bool
    days_left: int
    reason: str = ""

    @property
    def blocks(self) -> bool:
        return self.status in {
            LicenseStatus.EXPIRED, LicenseStatus.REVOKED,
            LicenseStatus.SUSPENDED, LicenseStatus.INVALID,
        }

    @property
    def should_warn(self) -> bool:
        return self.status is LicenseStatus.GRACE or (
            self.status is LicenseStatus.ACTIVE and self.days_left <= 30
        )


def issue(license_: License, secret: str) -> str:
    """Mint a token. Runs on our side only; the customer never gets the secret."""
    payload = {
        "v": TOKEN_VERSION,
        "id": license_.license_id,
        "tenant": license_.tenant_code,
        "plan": license_.plan,
        "issued": license_.issued_at.isoformat(),
        "until": license_.valid_until.isoformat(),
        "grace": license_.grace_days,
        "modules": list(license_.modules),
        "limits": {
            "max_plants": license_.limits.max_plants,
            "max_equipment": license_.limits.max_equipment,
            "max_users": license_.limits.max_users,
            "max_external_users": license_.limits.max_external_users,
        },
        "fingerprint": license_.database_fingerprint,
    }
    body = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    return f"{body}.{_sign(body, secret)}"


def verify(token: str, secret: str) -> License:
    """Signature first, contents second. Parsing an unverified payload is how
    a forged token gets to choose its own plan."""
    try:
        body, _, signature = token.strip().partition(".")
    except AttributeError as exc:
        raise MalformedToken("token is not a string") from exc
    if not body or not signature:
        raise MalformedToken("token must be <payload>.<signature>")
    if not hmac.compare_digest(signature, _sign(body, secret)):
        raise BadSignature("signature does not match")

    try:
        payload = json.loads(_b64decode(body))
    except (ValueError, TypeError) as exc:
        raise MalformedToken("payload is not valid JSON") from exc
    if payload.get("v") != TOKEN_VERSION:
        raise MalformedToken(f"unsupported token version {payload.get('v')}")

    limits = payload.get("limits") or {}
    return License(
        tenant_code=payload["tenant"],
        plan=payload["plan"],
        issued_at=date.fromisoformat(payload["issued"]),
        valid_until=date.fromisoformat(payload["until"]),
        license_id=payload["id"],
        grace_days=int(payload.get("grace", 15)),
        limits=LicenseLimits(
            max_plants=limits.get("max_plants"),
            max_equipment=limits.get("max_equipment"),
            max_users=limits.get("max_users"),
            max_external_users=limits.get("max_external_users"),
        ),
        modules=tuple(payload.get("modules") or ()),
        database_fingerprint=payload.get("fingerprint", ""),
    )


def evaluate(
    license_: License,
    *,
    today: date | None = None,
    revoked: frozenset[str] = frozenset(),
    suspended: bool = False,
    database_fingerprint: str | None = None,
) -> LicenseVerdict:
    today = today or datetime.now(UTC).date()
    days_left = license_.valid_until.toordinal() - today.toordinal()

    if license_.license_id in revoked:
        return LicenseVerdict(LicenseStatus.REVOKED, True, days_left, "licencia revocada")
    if suspended:
        return LicenseVerdict(LicenseStatus.SUSPENDED, True, days_left, "servicio suspendido")
    if (
        license_.database_fingerprint
        and database_fingerprint is not None
        and license_.database_fingerprint != database_fingerprint
    ):
        # The licence was issued for one customer database. Pointing the
        # deployment at a different one is a different installation.
        return LicenseVerdict(
            LicenseStatus.INVALID, True, days_left,
            "la licencia no corresponde a esta base de datos",
        )
    if days_left >= 0:
        return LicenseVerdict(LicenseStatus.ACTIVE, False, days_left)
    if today <= license_.grace_until():
        return LicenseVerdict(
            LicenseStatus.GRACE, True, days_left,
            "licencia vencida: el sistema está en solo lectura",
        )
    return LicenseVerdict(LicenseStatus.EXPIRED, True, days_left, "licencia vencida")


def check_limit(license_: License, resource: str, current_count: int) -> bool:
    """`True` when one more of `resource` fits. No limit means no ceiling."""
    limit = license_.limits.limit_for(resource)
    return limit is None or current_count < limit


def database_fingerprint(*, tenant_code: str, database_name: str, host: str) -> str:
    """Stable identifier of one customer database. Not a secret — its job is to
    detect a moved or copied installation, not to hide anything."""
    material = f"{tenant_code}|{database_name}|{host}".lower().encode()
    return hashlib.sha256(material).hexdigest()[:32]


def _sign(body: str, secret: str) -> str:
    digest = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return _b64encode(digest)


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
