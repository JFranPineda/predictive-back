"""The date a licence is judged by.

The server clock is an input, not a source of truth: a server without NTP, a
container just created or a manual time-zone change all give wrong dates. The
installation remembers the highest date it has seen under the licence in
force, and a clock more than a day below it puts the system in read-only with
the dates its IT needs to fix the clock. Read-only, never blocked: a wrong
clock must not stop a plant.

The floor is the highest of three dates: the licence's issue date (signed by
us), the stored reference, and the newest reading recorded after it (server
time, never the date the technician typed). It restarts with every licence,
which is the way out of a clock that once jumped forward by mistake.

The stored reference is signed with a key derived from the installation. Not
to hide it — anyone on the server can derive the key — but so a corrupted or
hand-edited value reads as missing instead of as a date seventy years ahead.
Missing means the current time is trusted.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from modules.licensing.domain.license import License

TOLERANCE = timedelta(hours=24)
# How stale the stored reference may get before it is written again: at most
# one write an hour per tenant, not one per request.
REFRESH = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class ClockReference:
    license_id: str
    seen_at: datetime
    # Readings with a primary key above this were recorded under this
    # reference; older ones, perhaps under a wrong clock, do not count.
    reading_baseline: int = 0


def clock_floor(
    license_: License, *, reference: ClockReference | None, latest_reading_at: datetime | None
) -> datetime:
    floor = datetime.combine(license_.issued_at, time.min, tzinfo=UTC)
    if reference is None or reference.license_id != license_.license_id:
        return floor
    floor = max(floor, reference.seen_at)
    return max(floor, latest_reading_at) if latest_reading_at is not None else floor


def is_behind(now: datetime, floor: datetime) -> bool:
    return now < floor - TOLERANCE


def advanced(
    reference: ClockReference | None, *, license_id: str, now: datetime, reading_baseline: int
) -> ClockReference | None:
    """The reference to store now, or None when nothing needs writing. It
    never moves back."""
    if reference is None or reference.license_id != license_id:
        return ClockReference(license_id=license_id, seen_at=now, reading_baseline=reading_baseline)
    if now > reference.seen_at + REFRESH:
        return replace(reference, seen_at=now)
    return None


def sign_reference(reference: ClockReference, *, tenant: str, installation_id: str) -> dict[str, Any]:
    body = {
        "license": reference.license_id,
        "seen_at": reference.seen_at.isoformat(),
        "baseline": reference.reading_baseline,
    }
    return {**body, "sig": _mac(body, tenant, installation_id)}


def read_reference(stored: object, *, tenant: str, installation_id: str) -> ClockReference | None:
    """A reference that does not check out is missing, never an error."""
    if not isinstance(stored, dict) or not isinstance(stored.get("sig"), str):
        return None
    body = {key: stored.get(key) for key in ("license", "seen_at", "baseline")}
    try:
        if not hmac.compare_digest(stored["sig"], _mac(body, tenant, installation_id)):
            return None
        seen_at = datetime.fromisoformat(str(body["seen_at"]))
        if seen_at.tzinfo is None:
            return None
        return ClockReference(
            license_id=str(body["license"]), seen_at=seen_at, reading_baseline=int(body["baseline"])
        )
    except (TypeError, ValueError):
        return None


def _mac(body: dict[str, Any], tenant: str, installation_id: str) -> str:
    key = hashlib.sha256(f"predictive-clock|{installation_id}".encode()).digest()
    message = json.dumps({**body, "tenant": tenant}, sort_keys=True, default=str).encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()
