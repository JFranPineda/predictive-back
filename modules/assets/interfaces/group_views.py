"""The assets list, one row per train (V3-05)."""

from __future__ import annotations

from collections import Counter

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.assets.infrastructure.group_overview import (
    GroupOverview,
    OverviewFilter,
    effective_of,
    train_overview,
)
from modules.assets.interfaces.serializers import EquipmentSerializer
from modules.security.application.access import allowed_area_ids

PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


class TrainOverviewView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        language = getattr(request, "language", "es")
        params = request.query_params
        rows = train_overview(
            request.company_id,
            allowed_area_ids(request.user, request.company_id),
            OverviewFilter(
                text=(params.get("q") or "").strip(),
                area=params.get("area") or "",
                kind=params.get("kind") or "",
                equipment_type=params.get("type") or "",
                status=params.get("status") or "",
            ),
            language,
        )
        page, next_cursor = _page(rows, params.get("cursor"),
                                  min(int(params.get("limit") or PAGE_SIZE), MAX_PAGE_SIZE))
        context = {"language": language}
        return Response({
            "items": [_train(row, context, language) for row in page],
            "next_cursor": next_cursor,
            # Over everything the filter matched, not the page on screen.
            "totals": _totals(rows),
        })


def _page(rows: list[GroupOverview], cursor: str | None, limit: int):
    """Rows are ordered by (name, id); the cursor is the id of the last one
    seen, so a train renamed between pages is not listed twice."""
    start = 0
    if cursor:
        seen = int(cursor)
        start = next((i + 1 for i, row in enumerate(rows) if row.group.id == seen), len(rows))
    page = rows[start:start + limit]
    more = start + limit < len(rows)
    return page, (str(page[-1].group.id) if more and page else None)


def _train(row: GroupOverview, context: dict, language: str) -> dict:
    group = row.group
    area = group.sector.area
    return {
        "id": group.id,
        "code": group.code,
        "name": group.name,
        "kind": {"code": group.kind.code, "name": group.kind.translated("name", language)}
        if group.kind else None,
        "area": {"id": area.id, "code": area.code, "name": area.name},
        "sector": {"id": group.sector_id, "name": group.sector.name},
        "status": _status(row.status),
        "equipment_count": len(row.equipments),
        "equipments": [
            {**EquipmentSerializer(machine, context=context).data,
             "effective_status": _status(effective_of(machine, language))}
            for machine in row.equipments
        ],
    }


def _status(status) -> dict:
    return {"code": status.code, "name": status.name, "color": status.color,
            "is_condition": status.is_condition}


def _totals(rows: list[GroupOverview]) -> dict:
    by_code = Counter(row.status.code for row in rows)
    return {
        "trains": len(rows),
        "equipments": sum(len(row.equipments) for row in rows),
        "alarm": by_code.get("alarm", 0),
        "shutdown": by_code.get("shutdown", 0),
        "not_measured": sum(1 for row in rows if not row.status.is_condition),
    }
