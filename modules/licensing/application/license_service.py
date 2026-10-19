"""Reads and evaluates a tenant's licence, once per request.

It used to cache the verdict for five minutes. That was wrong: the cache is
per process, so revoking a licence from the shell left every running worker
still serving the customer until its own copy expired. A revocation that lands
"eventually, per worker" is not a revocation.

The check is one indexed lookup on a table with one row per contract. If it
ever shows up in a profile, the fix is a shared cache with explicit
invalidation, not a local one that lies.

The same goes for what the verdict is checked against (v4 Phase 2): the
installation's identifiers and the remembered date are read on every request,
so a database swapped under a running process is noticed on the next one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from django.utils import timezone

from modules.licensing.domain.clock import advanced, clock_floor
from modules.licensing.domain.license import (
    License,
    LicenseError,
    LicenseStatus,
    LicenseVerdict,
    TrustedKeys,
    evaluate,
    lapsed_reason,
    verify,
)
from modules.licensing.domain.usage import Usage, limit_message

# How often the same non-fatal condition is written to the event log. Without
# this, a blocked tenant writes one row per request.
EVENT_THROTTLE = timedelta(hours=1)


def current_verdict(tenant_code: str, *, keys: TrustedKeys, suspended: bool = False) -> LicenseVerdict:
    from modules.licensing.infrastructure.models import Tenant

    record = latest_record(tenant_code)
    if record is None:
        reason = lapsed_reason("No hay licencia para este cliente")
        return LicenseVerdict(LicenseStatus.INVALID, True, 0, reason)

    try:
        license_ = verify(record.token, keys)
    except LicenseError as exc:
        _log(tenant_code, "blocked", f"token inválido: {exc}")
        return LicenseVerdict(LicenseStatus.INVALID, True, 0, lapsed_reason("La licencia no es válida"))

    from modules.licensing.infrastructure.installation import installation_id, observed_installation

    tenant = Tenant.objects.filter(code=tenant_code).first()
    now = datetime.now(UTC)
    installation = installation_id()
    verdict = evaluate(
        license_,
        now=now,
        revoked=frozenset({record.license_id}) if record.is_revoked else frozenset(),
        suspended=suspended,
        database_fingerprint=(tenant.database_fingerprint or None) if tenant else None,
        # Only a licence bound to an installation pays for reading the three.
        installation=(
            observed_installation(tenant_code, installation=installation)
            if license_.installation.is_bound else None
        ),
        clock_floor=_clock_floor(tenant, license_, now, installation) if tenant else None,
    )
    if verdict.lapsed:
        _log(tenant_code, "blocked", verdict.reason)
    elif verdict.read_only:
        _log(tenant_code, "degraded", verdict.reason)
    return verdict


def _clock_floor(tenant, license_: License, now: datetime, installation: str) -> datetime:
    """The highest date seen under this licence, moved forward when the clock
    is ahead of it (at most once an hour)."""
    from modules.licensing.infrastructure.clock_store import (
        latest_reading_after,
        load_reference,
        reading_baseline,
        store_reference,
    )
    from modules.licensing.infrastructure.context import ensure_registered

    alias = ensure_registered(tenant.code)
    reference = load_reference(tenant, license_id=license_.license_id, installation_id=installation)
    floor = clock_floor(
        license_,
        reference=reference,
        latest_reading_at=latest_reading_after(alias, reference.reading_baseline) if reference else None,
    )
    update = advanced(
        reference, license_id=license_.license_id, now=now,
        reading_baseline=reference.reading_baseline if reference else reading_baseline(alias),
    )
    if update is not None:
        store_reference(tenant, update, installation_id=installation)
    return floor


def store_licence(tenant, license_: License, token: str, *, kind: str, detail: str) -> None:
    """The record enforcement reads from now on: the newest term wins."""
    from modules.licensing.infrastructure.models import LicenseEvent, LicenseRecord

    LicenseRecord.objects.create(
        tenant=tenant, license_id=license_.license_id, token=token, plan=license_.plan,
        issued_at=license_.issued_at, valid_until=license_.valid_until, grace_days=license_.grace_days,
        modules=list(license_.modules),
        limits={
            "max_plants": license_.limits.max_plants,
            "max_equipment": license_.limits.max_equipment,
            "max_users": license_.limits.max_users,
            "max_external_users": license_.limits.max_external_users,
        },
    )
    LicenseEvent.objects.create(tenant=tenant, kind=kind, detail=detail[:300])


class PlanLimitReachedError(Exception):
    """One more would exceed the plan; the message says so in the customer's words."""


def plan_usage(tenant_code: str, resource: str, used: int, *, keys: TrustedKeys) -> Usage:
    """How much of the plan is used. No licence on record means no ceiling
    (a development database); an invalid one leaves no room at all."""
    record = latest_record(tenant_code)
    if record is None:
        return Usage(resource, used, None)
    try:
        license_ = verify(record.token, keys)
    except LicenseError:
        return Usage(resource, used, 0)
    return Usage(resource, used, license_.limits.limit_for(resource))


def ensure_room(tenant_code: str, resource: str, used: int, *, keys: TrustedKeys, adding: int = 1) -> Usage:
    """All or nothing: a load that does not fit whole creates none of it."""
    usage = plan_usage(tenant_code, resource, used, keys=keys)
    if not usage.fits(adding):
        _log(tenant_code, "limit_reached", f"{resource}={used}+{adding}")
        raise PlanLimitReachedError(limit_message(usage, adding))
    return usage


def latest_record(tenant_code: str):
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
