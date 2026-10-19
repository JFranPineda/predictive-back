"""Where the remembered date lives: the tenant's row in the control plane and
the installation file, both signed. The newest readable copy for the licence
in force wins; an unreadable one is ignored."""

from __future__ import annotations

from datetime import datetime

from django.db import DatabaseError, transaction
from django.db.models import Max

from modules.licensing.domain.clock import ClockReference, read_reference, sign_reference
from modules.licensing.infrastructure.installation import read_state, write_state


def load_reference(tenant, *, license_id: str, installation_id: str) -> ClockReference | None:
    copies = (tenant.clock, read_state().get("clocks", {}).get(tenant.code))
    readable = [
        reference
        for reference in (read_reference(copy, tenant=tenant.code, installation_id=installation_id)
                          for copy in copies)
        if reference is not None and reference.license_id == license_id
    ]
    return max(readable, key=lambda reference: reference.seen_at, default=None)


def store_reference(tenant, reference: ClockReference, *, installation_id: str) -> None:
    from modules.licensing.infrastructure.models import Tenant

    signed = sign_reference(reference, tenant=tenant.code, installation_id=installation_id)
    Tenant.objects.filter(pk=tenant.pk).update(clock=signed)
    state = read_state()
    clocks = state.get("clocks") if isinstance(state.get("clocks"), dict) else {}
    write_state({**state, "clocks": {**clocks, tenant.code: signed}})


def reading_baseline(alias: str) -> int:
    """The newest reading's key: readings above it are recorded from now on."""
    from modules.measurements.infrastructure.models import Reading

    try:
        with transaction.atomic(using=alias):
            return Reading.objects.using(alias).aggregate(top=Max("pk"))["top"] or 0
    except DatabaseError:
        return 0


def latest_reading_after(alias: str, baseline: int) -> datetime | None:
    """Server time of the newest reading recorded after the baseline. The
    date a technician typed (`taken_at`) never counts: one typo would leave
    the plant in read-only."""
    from modules.measurements.infrastructure.models import Reading

    try:
        with transaction.atomic(using=alias):
            return Reading.objects.using(alias).filter(pk__gt=baseline).aggregate(
                latest=Max("created_at")
            )["latest"]
    except DatabaseError:
        return None
