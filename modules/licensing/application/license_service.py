"""Reads and evaluates a tenant's licence, once per request.

It used to cache the verdict for five minutes. That was wrong: the cache is
per process, so revoking a licence from the shell left every running worker
still serving the customer until its own copy expired. A revocation that lands
"eventually, per worker" is not a revocation.

The check is one indexed lookup on a table with one row per contract. If it
ever shows up in a profile, the fix is a shared cache with explicit
invalidation, not a local one that lies.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from django.utils import timezone

from modules.licensing.domain.license import (
    LicenseError,
    LicenseStatus,
    LicenseVerdict,
    evaluate,
    verify,
)
from modules.licensing.domain.usage import Usage, limit_message

# How often the same non-fatal condition is written to the event log. Without
# this, a blocked tenant writes one row per request.
EVENT_THROTTLE = timedelta(hours=1)


def current_verdict(tenant_code: str, *, secret: str, suspended: bool = False) -> LicenseVerdict:
    from modules.licensing.infrastructure.models import Tenant

    record = _latest_record(tenant_code)
    if record is None:
        return LicenseVerdict(LicenseStatus.INVALID, True, 0, "no hay licencia para este cliente")

    try:
        license_ = verify(record.token, secret)
    except LicenseError as exc:
        _log(tenant_code, "blocked", f"token inválido: {exc}")
        return LicenseVerdict(LicenseStatus.INVALID, True, 0, "licencia no válida")

    fingerprint = (
        Tenant.objects.filter(code=tenant_code)
        .values_list("database_fingerprint", flat=True)
        .first()
        or None
    )
    verdict = evaluate(
        license_,
        today=datetime.now(UTC).date(),
        revoked=frozenset({record.license_id}) if record.is_revoked else frozenset(),
        suspended=suspended,
        database_fingerprint=fingerprint,
    )
    if verdict.blocks:
        _log(tenant_code, "blocked", verdict.reason)
    elif verdict.read_only:
        _log(tenant_code, "degraded", verdict.reason)
    return verdict


class PlanLimitReachedError(Exception):
    """One more would exceed the plan; the message says so in the customer's words."""


def plan_usage(tenant_code: str, resource: str, used: int, *, secret: str) -> Usage:
    """How much of the plan is used. No licence on record means no ceiling
    (a development database); an invalid one leaves no room at all."""
    record = _latest_record(tenant_code)
    if record is None:
        return Usage(resource, used, None)
    try:
        license_ = verify(record.token, secret)
    except LicenseError:
        return Usage(resource, used, 0)
    return Usage(resource, used, license_.limits.limit_for(resource))


def ensure_room(tenant_code: str, resource: str, used: int, *, secret: str, adding: int = 1) -> Usage:
    """All or nothing: a load that does not fit whole creates none of it."""
    usage = plan_usage(tenant_code, resource, used, secret=secret)
    if not usage.fits(adding):
        _log(tenant_code, "limit_reached", f"{resource}={used}+{adding}")
        raise PlanLimitReachedError(limit_message(usage, adding))
    return usage


def _latest_record(tenant_code: str):
    from modules.licensing.infrastructure.models import LicenseRecord

    # Newest contract first; a revoked one still wins over an older valid one,
    # because reviving an expired licence by revoking its replacement would be
    # a hole.
    return (
        LicenseRecord.objects.filter(tenant__code=tenant_code)
        .order_by("-valid_until", "-created_at")
        .first()
    )


def _log(tenant_code: str, kind: str, detail: str) -> None:
    from modules.licensing.infrastructure.models import LicenseEvent, Tenant

    tenant = Tenant.objects.filter(code=tenant_code).first()
    if tenant is None:
        return
    recent = LicenseEvent.objects.filter(
        tenant=tenant, kind=kind, at__gte=timezone.now() - EVENT_THROTTLE
    ).exists()
    if not recent:
        LicenseEvent.objects.create(tenant=tenant, kind=kind, detail=detail[:300])
