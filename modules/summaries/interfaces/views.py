from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.assets.models import Equipment
from modules.summaries.domain.rollup import EquipmentStatus, by_technique
from modules.thresholds.domain.entities import Status, StatusKind


class PlantSummaryView(APIView):
    """The traffic light. One per technique, because a pump can be in alarm on
    vibration and fine on thermography."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        language = getattr(request, "language", "es")
        queryset = (
            Equipment.objects.for_company(request.company_id)
            .select_related(
                "asset_group__sector__area", "asset_group__kind",
                "condition_status", "availability_status",
            )
        )
        if request.query_params.get("plant"):
            queryset = queryset.filter(
                asset_group__sector__area__plant_id=request.query_params["plant"]
            )

        from modules.security.application.access import allowed_area_ids

        areas = allowed_area_ids(request.user, request.company_id)
        if areas is not None:
            queryset = queryset.filter(asset_group__sector__area_id__in=areas)

        rows = [_to_domain(item, language) for item in queryset]
        summaries = by_technique(rows)
        techniques = _technique_names(language)

        return Response([
            {
                "technique_code": code,
                "technique_name": techniques.get(code, code),
                "nodes": [_node(node) for node in nodes],
            }
            for code, nodes in summaries.items()
        ])


def _to_domain(item: Equipment, language: str) -> EquipmentStatus:
    area = item.asset_group.sector.area
    return EquipmentStatus(
        equipment_id=item.id,
        name=item.name,
        area_id=area.id,
        area_label=f"{area.code} - {area.name}",
        sector_id=item.asset_group.sector_id,
        sector_label=item.asset_group.sector.name,
        asset_group_id=item.asset_group_id,
        asset_group_label=item.asset_group.name,
        technique_code="vibration",
        condition=_status(item.condition_status, language),
        availability=_status(item.availability_status, language),
    )


def _status(row, language: str) -> Status | None:
    if row is None:
        return None
    return Status(
        code=row.code, name=row.translated("name", language), kind=StatusKind(row.kind),
        severity=row.severity, color=row.color, requires_action=row.requires_action,
        is_terminal=row.is_terminal, measurable=row.measurable,
    )


def _node(node) -> dict:
    return {
        "key": node.key,
        "label": node.label,
        "level": node.level,
        "total": node.total,
        "evaluated": node.evaluated,
        "coverage": node.coverage,
        "worst": _status_payload(node.worst),
        "counts": [
            {"status": _status_payload(count.status), "count": count.count}
            for count in node.counts
        ],
        "children": [_node(child) for child in node.children],
    }


def _status_payload(status: Status) -> dict:
    return {
        "code": status.code, "name": status.name, "kind": status.kind.value,
        "severity": status.severity, "color": status.color,
        "measurable": status.measurable, "requires_action": status.requires_action,
    }


def _technique_names(language: str) -> dict[str, str]:
    from modules.measurements.models import Technique

    return {row.code: row.translated("name", language) for row in Technique.objects.all()}
