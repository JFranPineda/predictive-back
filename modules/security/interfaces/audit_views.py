"""The audit trail, as the maintenance manager reads it.

"Solo lectura + auditoría" is the manager's access: see everything, change
nothing, and be able to answer "who changed this value, and when". The rows
are never editable from here or anywhere else — a log you can edit is a log
of what somebody wanted on record.
"""

from __future__ import annotations

from django.utils.dateparse import parse_date
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.core.infrastructure.models import AuditLog
from modules.security.application.access import build_actor

PAGE_SIZE = 50


class AuditLogView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        actor = build_actor(request.user, request.company_id)
        if not actor.has("core.view_audit"):
            raise PermissionDenied("Falta el permiso core.view_audit")

        queryset = (
            AuditLog.objects.filter(company_id=request.company_id)
            .select_related("actor")
            .order_by("-at", "-id")
        )
        params = request.query_params
        if params.get("action"):
            # "reading" matches every reading.* action: one filter per family.
            queryset = queryset.filter(action__startswith=params["action"])
        if params.get("user"):
            queryset = queryset.filter(actor_id=int(params["user"]))
        if params.get("object_type"):
            queryset = queryset.filter(object_type=params["object_type"])
        if params.get("since"):
            since = parse_date(params["since"])
            if since:
                queryset = queryset.filter(at__date__gte=since)
        # Keyset on (at, id): the log only grows, and OFFSET on a table that
        # only grows gets slower every day it is useful.
        if params.get("before"):
            queryset = queryset.filter(id__lt=int(params["before"]))

        rows = list(queryset[: PAGE_SIZE + 1])
        more = len(rows) > PAGE_SIZE
        rows = rows[:PAGE_SIZE]
        return Response({
            "items": [
                {
                    "id": row.id,
                    "at": row.at.isoformat(),
                    "action": row.action,
                    "object_type": row.object_type,
                    "object_id": row.object_id,
                    "actor": row.actor.get_full_name() if row.actor else None,
                    "actor_initials": row.actor.initials if row.actor else "",
                    "before": row.before,
                    "after": row.after,
                    "ip": row.ip,
                }
                for row in rows
            ],
            "next_before": rows[-1].id if more and rows else None,
        })
