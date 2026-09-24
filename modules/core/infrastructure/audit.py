"""Who changed what, and when — the record the maintenance manager audits.

The table existed from the start and nothing ever wrote to it, which is worse
than not having one: an empty audit log reads as "nothing happened". This is
the single writer, called at the places where a field value, an access or a
permission actually changes.

It runs inside the caller's transaction on purpose. A change that commits
while its audit row fails is exactly the unaudited change the log exists to
rule out.
"""

from __future__ import annotations

from typing import Any

from modules.core.infrastructure.models import AuditLog


def record(
    request,
    action: str,
    *,
    object_type: str = "",
    object_id: Any = "",
    before: dict | None = None,
    after: dict | None = None,
    actor=None,
) -> None:
    user = actor if actor is not None else getattr(request, "user", None)
    AuditLog.objects.create(
        company_id=getattr(request, "company_id", None),
        actor=user if getattr(user, "is_authenticated", False) else None,
        action=action,
        object_type=object_type,
        object_id=str(object_id or ""),
        before=before,
        after=after,
        ip=_client_ip(request),
    )


def _client_ip(request) -> str | None:
    """The first hop behind a tunnel or proxy.

    Informational only: X-Forwarded-For is written by whoever sends the
    request, so it identifies a device, never proves one.
    """
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None
