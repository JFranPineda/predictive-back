"""Every answered write becomes a row of the log (Q20).

Told by `RequestObserverMiddleware` after the view has answered, so it knows
who the user was (DRF has authenticated him by then), what the body carried
and how it ended. Reads are not events; the browser reports its own clicks
and page changes through `activity/events/`.
"""

from __future__ import annotations

import json

from django.utils import timezone

from modules.activity.domain.describe import LOGIN_PATHS, describe_request

READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def observe(request, response, view_func, view_kwargs) -> None:
    if request.method in READ_METHODS:
        return
    fields, files = _carried(request)
    login_email = _login_email(request) if _is_login(request.path) else ""
    described = describe_request(
        method=request.method,
        path=request.path,
        status=response.status_code,
        fields=fields,
        files=files,
        login_email=login_email,
        owner=_owner(request, files),
    )
    if described is None:
        return

    user = getattr(request, "user", None)
    user = user if getattr(user, "is_authenticated", False) else None
    company_id = getattr(request, "company_id", None)
    if user is None and login_email:
        user, company_id = _login_user(login_email, request)
        if described.kind == "login_failed":
            user = None
    write(
        request,
        company_id=company_id,
        user=user,
        kind=described.kind,
        event=described.event,
        description=described.description,
        path=request.path[:200],
        method=request.method,
        status_code=response.status_code,
        object_type=described.object_type,
        object_id=described.object_id,
    )


def write(
    request,
    *,
    company_id,
    user,
    kind,
    event,
    description,
    path="",
    method="",
    status_code=None,
    object_type="",
    object_id="",
    at=None,
) -> None:
    from modules.activity.infrastructure.models import ActivityEvent

    ActivityEvent.objects.create(
        company_id=company_id,
        user=user,
        user_label=_label(user),
        kind=kind,
        event=event[:80],
        description=description[:300],
        path=path[:200],
        method=method,
        status_code=status_code,
        object_type=object_type[:60],
        object_id=str(object_id or "")[:40],
        ip=_ip(request),
        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:200],
        at=at or timezone.now(),
    )


def _carried(request) -> tuple[list[str], list[str]]:
    """Which fields the write named, and the names of the files it sent."""
    files = [upload.name for upload in request.FILES.values()] if request.FILES else []
    if request.content_type == "application/json":
        try:
            body = json.loads(request.body or b"{}")
        except Exception:  # stream already consumed, or not JSON
            body = {}
        return (list(body) if isinstance(body, dict) else []), files
    return [key for key in request.POST if key not in request.FILES], files


def _owner(request, files) -> tuple[str, str] | None:
    if not files or not request.POST.get("owner_type"):
        return None
    return request.POST["owner_type"], str(request.POST.get("owner_id") or "")


def _is_login(path: str) -> bool:
    return any(f"/api/v1/{login}/" in path for login in LOGIN_PATHS)


def _login_email(request) -> str:
    try:
        body = json.loads(request.body or b"{}")
    except Exception:
        body = request.POST
    if not hasattr(body, "get"):
        return ""
    return str(body.get("email") or body.get("username") or "").strip()[:120]


def _login_user(email: str, request):
    from modules.security.application.access import resolve_company
    from modules.security.models import User

    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        return None, None
    try:
        return user, resolve_company(user, request.headers.get("X-Company-Id"))
    except (PermissionError, ValueError):
        return user, None


def _label(user) -> str:
    if user is None:
        return ""
    name = user.get_full_name() if hasattr(user, "get_full_name") else ""
    return (name or getattr(user, "email", "") or str(user))[:160]


def _ip(request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None
