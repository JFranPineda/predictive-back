"""Licensing.

A licence says which customer may use PREDICTIVE, for which period, with
which modules and ceilings. It is a signed token: `base64url(payload)` dot
`base64url(signature)`.

Be honest about what a key does and does not do:

- It **does** stop the application from serving a tenant whose contract
  ended, and it does it at a single chokepoint instead of in a hundred views.
- It **does not** encrypt the customer's database. They own those rows and can
  read them with `psql` any day.

Since the application also runs on the customer's server, issuing and
verifying are separate capabilities (v2): we sign with an Ed25519 key that
never leaves our issuing machine, and every installation verifies with the
public half shipped in the program. v1 signed with a shared HMAC secret, which
would have meant installing the signing credential everywhere; it is accepted
only while the move to v2 lasts, and only where that secret is configured.

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
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from modules.licensing.domain.clock import is_behind
from modules.licensing.domain.installation import InstallationFingerprint, belongs_to
from modules.licensing.domain.signing import SigningKeyError, load_public_key

TOKEN_VERSION = 2
LEGACY_TOKEN_VERSION = 1
SUPPORTED_VERSIONS = (LEGACY_TOKEN_VERSION, TOKEN_VERSION)


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
    OTHER_INSTALLATION = "other_installation"
    CLOCK_BEHIND = "clock_behind"


OTHER_INSTALLATION_REASON = (
    "Esta licencia es de otra instalación: el sistema queda en solo lectura. Para reactivarla, "
    "envía a 1A-MIG lo que muestra `manage.py license fingerprint` en este servidor y te "
    "enviaremos una licencia para él."
)


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
    # copy of the data does not silently reuse the licence. Only checked for a
    # licence with no installation, which v1 tokens never have.
    database_fingerprint: str = ""
    installation: InstallationFingerprint = field(default_factory=InstallationFingerprint)

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


@dataclass(frozen=True, slots=True)
class TrustedKeys:
    """What a verifier holds. Never the signing key."""

    public_key: str
    # v1 (HMAC) tokens, during the move to v2 only. Empty refuses them.
    legacy_secret: str = ""


def issue(license_: License, signing_key: Ed25519PrivateKey) -> str:
    """Mint a v2 token. Runs on our issuing machine only."""
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
    if license_.installation.is_bound:
        payload["installation"] = {
            "id": license_.installation.installation_id,
            "pg": license_.installation.pg_system_id,
            "machine": license_.installation.machine_id,
        }
    body = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    return f"{body}.{_b64encode(signing_key.sign(body.encode()))}"


def verify(token: str, keys: TrustedKeys) -> License:
    """Signature first, contents second. Parsing an unverified payload is how
    a forged token gets to choose its own plan.

    The version is the one field read before the signature, because it picks
    the algorithm. It cannot buy a weaker check: each version has its own key
    material, and v1 has none unless the legacy secret is configured."""
    body, signature = _split(token)
    version = _version_of(body)
    if version == TOKEN_VERSION:
        _check_ed25519(body, signature, keys.public_key)
    else:
        _check_hmac(body, signature, keys.legacy_secret)
    return _license_from(_read(body))


def token_version(token: str) -> int | None:
    """The version a token claims, unverified. For dispatch and for listings."""
    try:
        return _version_of(_split(token)[0])
    except MalformedToken:
        return None


def _split(token: str) -> tuple[str, str]:
    try:
        body, _, signature = token.strip().partition(".")
    except AttributeError as exc:
        raise MalformedToken("token is not a string") from exc
    if not body or not signature:
        raise MalformedToken("token must be <payload>.<signature>")
    return body, signature


def _read(body: str) -> dict[str, Any]:
    try:
        payload = json.loads(_b64decode(body))
    except (ValueError, TypeError) as exc:
        raise MalformedToken("payload is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise MalformedToken("payload is not an object")
    return payload


def _version_of(body: str) -> int:
    version = _read(body).get("v")
    # `True == 1` in Python; a version is an integer on the list, nothing else.
    if type(version) is not int or version not in SUPPORTED_VERSIONS:
        raise MalformedToken(f"unsupported token version {version!r}")
    return version


def _check_ed25519(body: str, signature: str, public_key: str) -> None:
    try:
        key = load_public_key(public_key)
    except SigningKeyError as exc:
        raise BadSignature(str(exc)) from exc
    try:
        key.verify(_b64decode(signature), body.encode())
    except (InvalidSignature, ValueError) as exc:
        raise BadSignature("signature does not match") from exc


def _check_hmac(body: str, signature: str, secret: str) -> None:
    if not secret:
        raise BadSignature("v1 tokens need the legacy secret, and none is configured")
    if not hmac.compare_digest(signature, _hmac(body, secret)):
        raise BadSignature("signature does not match")


def _license_from(payload: dict[str, Any]) -> License:
    limits = payload.get("limits") or {}
    installation = payload.get("installation") or {}
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
        installation=InstallationFingerprint(
            installation_id=str(installation.get("id", "")),
            pg_system_id=str(installation.get("pg", "")),
            machine_id=str(installation.get("machine", "")),
        ),
    )


def evaluate(
    license_: License,
    *,
    today: date | None = None,
    now: datetime | None = None,
    revoked: frozenset[str] = frozenset(),
    suspended: bool = False,
    database_fingerprint: str | None = None,
    installation: InstallationFingerprint | None = None,
    clock_floor: datetime | None = None,
) -> LicenseVerdict:
    """Worst first. An expired licence stays expired wherever it runs; the
    installation and the clock only ever take writing away, never reading."""
    now = now or datetime.now(UTC)
    today = today or now.date()
    days_left = license_.valid_until.toordinal() - today.toordinal()
    bound = license_.installation.is_bound

    if license_.license_id in revoked:
        return LicenseVerdict(LicenseStatus.REVOKED, True, days_left, "licencia revocada")
    if suspended:
        return LicenseVerdict(LicenseStatus.SUSPENDED, True, days_left, "servicio suspendido")
    if (
        not bound
        and license_.database_fingerprint
        and database_fingerprint is not None
        and license_.database_fingerprint != database_fingerprint
    ):
        # The licence was issued for one customer database. Pointing the
        # deployment at a different one is a different installation.
        return LicenseVerdict(
            LicenseStatus.INVALID, True, days_left,
            "la licencia no corresponde a esta base de datos",
        )
    if days_left < 0 and today > license_.grace_until():
        return LicenseVerdict(LicenseStatus.EXPIRED, True, days_left, "licencia vencida")
    if bound and installation is not None and not belongs_to(license_.installation, installation):
        return LicenseVerdict(LicenseStatus.OTHER_INSTALLATION, True, days_left, OTHER_INSTALLATION_REASON)
    if days_left < 0:
        return LicenseVerdict(
            LicenseStatus.GRACE, True, days_left,
            "licencia vencida: el sistema está en solo lectura",
        )
    if clock_floor is not None and is_behind(now, clock_floor):
        return LicenseVerdict(
            LicenseStatus.CLOCK_BEHIND, True, days_left,
            f"La fecha del servidor ({now:%Y-%m-%d %H:%M} UTC) es anterior a la última registrada "
            f"({clock_floor:%Y-%m-%d %H:%M} UTC): el sistema queda en solo lectura hasta que se "
            "corrija la hora del servidor.",
        )
    return LicenseVerdict(LicenseStatus.ACTIVE, False, days_left)


def check_limit(license_: License, resource: str, current_count: int) -> bool:
    """`True` when one more of `resource` fits. No limit means no ceiling."""
    limit = license_.limits.limit_for(resource)
    return limit is None or current_count < limit


def database_fingerprint(*, tenant_code: str, database_name: str, host: str) -> str:
    """Stable identifier of one customer database. Not a secret — its job is to
    detect a moved or copied installation, not to hide anything."""
    material = f"{tenant_code}|{database_name}|{host}".lower().encode()
    return hashlib.sha256(material).hexdigest()[:32]


def _hmac(body: str, secret: str) -> str:
    digest = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return _b64encode(digest)


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
