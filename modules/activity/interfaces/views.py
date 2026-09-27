"""The activity log as the administrator reads it (Q20), and the door the
browser reports its clicks through.

Read-only on purpose: no endpoint edits or deletes a row.
"""

from __future__ import annotations

import csv
from datetime import datetime, time, timedelta

from django.db.models import Count, Q
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.activity.domain.describe import KIND_LABELS, KINDS, clean_client_events
from modules.activity.infrastructure.models import ActivityEvent
from modules.activity.infrastructure.observer import write
from modules.core.domain.history import WINDOW_DAYS, window_for
from modules.security.infrastructure.access import build_actor

PAGE_SIZE = 50
EXPORT_LIMIT = 50_000


class ActivityListView(APIView):
    """`GET activity/?user=&kind=a,b&q=&since=&until=&before=` — newest first,
    keyset-paginated: the log only grows, so OFFSET would only get slower."""

    permission_classes = (IsAuthenticated,)

    def get(self, request):
        _require(request, "activity.view")
        rows = _filtered(request)
        window = _window(request)
        total = rows.count()
        counts = {
            row["kind"]: row["n"]
            for row in _filtered(request, with_kind=False).order_by().values("kind").annotate(n=Count("id"))
        }
        if request.query_params.get("before"):
            rows = rows.filter(id__lt=int(request.query_params["before"]))
        page = list(rows.select_related("user")[: PAGE_SIZE + 1])
        more = len(page) > PAGE_SIZE
        page = page[:PAGE_SIZE]
        return Response(
            {
                "items": [_payload(row) for row in page],
                "total": total,
                "counts": counts,
                "next_before": page[-1].id if more and page else None,
                "window": {
                    "since": window.start.isoformat(),
                    "until": window.end.isoformat(),
                    "days": WINDOW_DAYS,
                },
            }
        )


class ActivityActorsView(APIView):
    """`GET activity/actors/` — who appears in the log, for the user filter."""

    permission_classes = (IsAuthenticated,)

    def get(self, request):
        _require(request, "activity.view")
        rows = (
            ActivityEvent.objects.filter(company_id=request.company_id, user__isnull=False)
            .values("user_id", "user_label")
            .order_by("user_label")
            .distinct()
        )
        seen: dict[int, str] = {}
        for row in rows:
            seen.setdefault(row["user_id"], row["user_label"])
        return Response(
            {
                "users": [
                    {"id": key, "name": name} for key, name in sorted(seen.items(), key=lambda i: i[1])
                ],
                "kinds": [{"code": code, "label": KIND_LABELS[code]} for code in KINDS],
            }
        )


class ActivityEventsView(APIView):
    """`POST activity/events/` with `{"events": [...]}` — what the browser saw
    the user do. Only clicks, page changes and logouts are accepted."""

    permission_classes = (IsAuthenticated,)

    def post(self, request):
        raw = request.data.get("events")
        if not isinstance(raw, list):
            raise ValidationError("Se esperaba una lista de eventos")
        for event in clean_client_events(raw):
            write(
                request,
                company_id=request.company_id,
                user=request.user,
                kind=event.kind,
                event=event.event,
                description=event.description,
                path=event.path,
            )
        return Response(status=204)


class ActivityExportView(APIView):
    """`GET activity/export/` — the same filters, as a CSV the manager opens
    in Excel."""

    permission_classes = (IsAuthenticated,)

    def get(self, request):
        _require(request, "activity.export")
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        stamp = timezone.localtime().strftime("%Y%m%d-%H%M")
        response["Content-Disposition"] = f'attachment; filename="actividad-{stamp}.csv"'
        response.write("﻿")  # Excel reads UTF-8 only with the BOM
        writer = csv.writer(response)
        writer.writerow(["Fecha", "Hora", "Usuario", "Evento", "Descripción", "Ruta", "IP"])
        for row in _filtered(request)[:EXPORT_LIMIT].iterator():
            local = timezone.localtime(row.at)
            writer.writerow(
                [
                    local.strftime("%d/%m/%Y"),
                    local.strftime("%H:%M:%S"),
                    row.user_label or "—",
                    row.event,
                    row.description,
                    row.path,
                    row.ip or "",
                ]
            )
        return response


def _require(request, permission: str) -> None:
    actor = build_actor(request.user, request.company_id)
    if not actor.has(permission):
        raise PermissionDenied(f"Falta el permiso {permission}")


def _filtered(request, *, with_kind: bool = True):
    params = request.query_params
    rows = ActivityEvent.objects.filter(company_id=request.company_id)
    if params.get("user"):
        rows = rows.filter(user_id=int(params["user"]))
    kinds = [kind for kind in (params.get("kind") or "").split(",") if kind in KINDS]
    if kinds and with_kind:
        rows = rows.filter(kind__in=kinds)
    if params.get("q"):
        term = params["q"].strip()
        rows = rows.filter(
            Q(description__icontains=term) | Q(user_label__icontains=term) | Q(event__icontains=term)
        )
    window = _window(request)
    rows = rows.filter(
        at__gte=_start_of(window.start), at__lt=_start_of(window.end) + timedelta(days=1)
    )
    return rows.order_by("-at", "-id")


def _window(request):
    """Two weeks at a time (`core.domain.history`): what is older was filed
    on disk, and the screen says where."""
    params = request.query_params
    return window_for(
        parse_date(params.get("since") or ""),
        parse_date(params.get("until") or ""),
        timezone.localdate(),
    )


def _start_of(day) -> datetime:
    return timezone.make_aware(datetime.combine(day, time.min))


def _payload(row: ActivityEvent) -> dict:
    return {
        "id": row.id,
        "at": row.at.isoformat(),
        "user": {"id": row.user_id, "name": row.user_label} if row.user_label else None,
        "initials": _initials(row.user_label),
        "kind": row.kind,
        "event": row.event,
        "description": row.description,
        "path": row.path,
        "method": row.method,
        "status_code": row.status_code,
        "ip": row.ip,
    }


def _initials(label: str) -> str:
    words = [word for word in label.replace("@", " ").split() if word[:1].isalpha()]
    return "".join(word[0] for word in words[:2]).upper() or "·"
