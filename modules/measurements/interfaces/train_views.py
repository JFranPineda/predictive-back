"""Mediciones → one row per train for the chosen service (V3-06, V3-07)."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.measurements.infrastructure.train_index import ORDERS, TrainIndexRow, train_index
from modules.security.application.access import allowed_area_ids

PAGE_SIZE = 50


class TrainIndexView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        language = getattr(request, "language", "es")
        params = request.query_params
        order = params.get("order") if params.get("order") in ORDERS else "name"
        rows = train_index(
            request.company_id,
            allowed_area_ids(request.user, request.company_id),
            technique=params.get("technique") or "vibration",
            text=(params.get("q") or "").strip(),
            language=language,
            order=order,
        )
        start = int(params.get("offset") or 0)
        limit = min(int(params.get("limit") or PAGE_SIZE), 200)
        page = rows[start:start + limit]
        return Response({
            "items": [_row(row) for row in page],
            "count": len(rows),
            "next_offset": start + limit if start + limit < len(rows) else None,
            "areas": len({row.overview.group.sector.area_id for row in rows}),
        })


def _row(row: TrainIndexRow) -> dict:
    group = row.overview.group
    status = row.overview.status
    touched = row.last_intervention
    return {
        "id": group.id,
        "code": group.code,
        "name": group.name,
        "kind": group.kind.name if group.kind else "",
        "area": {"code": group.sector.area.code, "name": group.sector.area.name},
        "status": {"code": status.code, "name": status.name, "color": status.color},
        "measured_points": row.measured_points,
        "last_intervention": {"at": touched.at.isoformat(), "what": touched.what, "who": touched.who}
        if touched else None,
    }
