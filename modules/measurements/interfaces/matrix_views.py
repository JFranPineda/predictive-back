"""The record of values, in the shape the customer already reads it.

`TABLA DE TENDENCIAS.xls` puts one block per magnitude, rows grouped by
component and by side of the machine, and one column per date. That is not a
nostalgic choice: an analyst reads a row left to right to see a trend and
reads a column top to bottom to see one round. A flat list of readings serves
neither.

Editing happens in the same grid, one column at a time, because the column is
a visit and a visit is what carries the ownership rule.
"""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.assets.models import Equipment
from modules.measurements.models import Reading
from modules.security.application.access import build_actor
from modules.security.domain.policies import VisitRef, can_edit_visit

# The order the sheet prints them in.
SIDE_ORDER = {
    "free_end": 0,
    "coupling_end": 1,
    "opposite_coupling": 2,
    "inboard": 3,
    "outboard": 4,
    "custom": 5,
}


class EquipmentMatrixView(APIView):
    """Every reading of one machine train, grouped as the report groups it."""

    permission_classes = [IsAuthenticated]

    def get(self, request, equipment_id: int):
        language = getattr(request, "language", "es")
        equipment = (
            Equipment.objects.for_company(request.company_id)
            .select_related("asset_group__sector__area")
            .filter(id=equipment_id)
            .first()
        )
        if equipment is None:
            return Response({"type": "not_found", "status": 404}, status=404)

        scope = request.query_params.get("scope", "group")
        equipments = (
            list(equipment.asset_group.equipments.all())
            if scope == "group"
            else [equipment]
        )

        readings = (
            Reading.objects.for_company(request.company_id)
            .filter(point__equipment__in=equipments)
            .select_related(
                "point__equipment",
                "magnitude__default_unit",
                "unit",
                "condition_status",
                "service_visit__service_order__technique",
            )
            .order_by("taken_at", "point__number", "point__axis")
        )
        if request.query_params.get("technique"):
            readings = readings.filter(
                magnitude__technique__code=request.query_params["technique"]
            )

        actor = build_actor(request.user, request.company_id)
        columns: dict[str, dict] = {}
        blocks: dict[str, dict] = {}

        for reading in readings:
            # A column is a round, not an instant. The motor and the pump of
            # one train are visited hours apart, and keying by timestamp split
            # every round into two half-empty columns.
            column_key = _column_key(reading)
            column = columns.get(column_key)
            if column is None:
                columns[column_key] = _column(reading, actor, equipment)
            else:
                column["can_edit"] = column["can_edit"] or _editable(reading, actor, equipment)
            # One round covers the whole train, so a column spans the visit of
            # each machine in it. Keeping only the first lost the operating
            # conditions of the other one.
            if reading.service_visit_id:
                entry = columns[column_key]
                if reading.service_visit_id not in entry["visit_ids"]:
                    entry["visit_ids"].append(reading.service_visit_id)
                # Which of them is the machine that was asked for. A running
                # hour counter belongs to one machine, so merging the train's
                # visits blindly made it jump between two counters.
                if reading.point.equipment_id == equipment.id:
                    entry["primary_visit_id"] = reading.service_visit_id

            magnitude = reading.magnitude
            block = blocks.setdefault(
                _block_key(reading),
                {
                    "key": _block_key(reading),
                    "magnitude_code": magnitude.code,
                    "title": magnitude.translated("name", language),
                    "unit": reading.unit.code,
                    "aggregation": reading.aggregation,
                    "decimals": magnitude.decimals,
                    "rows": {},
                },
            )
            row = block["rows"].setdefault(
                reading.point_id,
                {
                    "point_id": reading.point_id,
                    "label": reading.point.label,
                    "number": reading.point.number,
                    "axis": reading.point.axis,
                    "side": reading.point.side,
                    "component": reading.point.equipment.name,
                    "component_id": reading.point.equipment_id,
                    "cells": {},
                },
            )
            row["cells"][column_key] = {
                "reading_id": reading.id,
                "value": str(reading.value) if reading.value is not None else None,
                "status_code": reading.condition_status.code if reading.condition_status else None,
                "status_color": reading.condition_status.color if reading.condition_status else None,
                "quality": reading.quality,
                "visit_id": reading.service_visit_id,
            }

        ordered_columns = sorted(columns.values(), key=lambda column: column["taken_at"])
        return Response({
            "equipment": {
                "id": equipment.id,
                "name": equipment.name,
                "tag": equipment.client_tag or equipment.asset_code,
                "group": equipment.asset_group.name,
                "area": f"{equipment.asset_group.sector.area.code} - "
                        f"{equipment.asset_group.sector.area.name}",
            },
            "scope": scope,
            "columns": ordered_columns,
            "blocks": [
                {
                    **block,
                    "rows": sorted(
                        (
                            {
                                **row,
                                "cells": [
                                    row["cells"].get(column["key"]) for column in ordered_columns
                                ],
                            }
                            for row in block["rows"].values()
                        ),
                        key=lambda row: (
                            row["component_id"],
                            SIDE_ORDER.get(row["side"], 9),
                            row["number"],
                            row["axis"],
                        ),
                    ),
                }
                for block in sorted(blocks.values(), key=lambda b: b["key"])
            ],
        })


def _block_key(reading: Reading) -> str:
    # Gs peak and Gs peak-to-peak are different criteria and get their own
    # block, exactly as the sheet separates velocity from envelope.
    return f"{reading.magnitude.code}:{reading.aggregation}"


def _column_key(reading: Reading) -> str:
    visit = reading.service_visit
    if visit is not None:
        return f"order:{visit.service_order_id}"
    return f"date:{reading.taken_at.date().isoformat()}"


def _editable(reading: Reading, actor, equipment: Equipment) -> bool:
    visit = reading.service_visit
    if visit is None:
        return False
    return can_edit_visit(
        actor,
        VisitRef(
            id=visit.id,
            area_id=equipment.asset_group.sector.area_id,
            participant_ids=frozenset(visit.participants.values_list("user_id", flat=True)),
            lead_analyst_id=None,
            is_closed=visit.is_closed,
            report_issued=False,
            visited_on=visit.visited_at.date(),
        ),
    )


def _column(reading: Reading, actor, equipment: Equipment) -> dict:
    visit = reading.service_visit
    return {
        "key": _column_key(reading),
        "visit_ids": [],
        "primary_visit_id": None,
        "taken_at": reading.taken_at.isoformat(),
        "date": reading.taken_at.date().isoformat(),
        "visit_id": visit.id if visit else None,
        "order_code": visit.service_order.code if visit else "",
        "technique": visit.service_order.technique.code if visit else "",
        "is_closed": visit.is_closed if visit else True,
        "can_edit": _editable(reading, actor, equipment),
    }
