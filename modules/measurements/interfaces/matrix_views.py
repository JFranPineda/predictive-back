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
from modules.measurements.domain.axes import axis_rank
from modules.measurements.domain.magnitude_order import block_sort_key
from modules.measurements.infrastructure.fixed_tables import planned_fixed
from modules.measurements.models import Reading
from modules.security.domain.policies import VisitRef, can_edit_visit
from modules.security.infrastructure.access import build_actor

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
        equipment = _equipment(request, equipment_id)
        if equipment is None:
            return Response({"type": "not_found", "status": 404}, status=404)
        return Response(build_matrix(request, equipment, request.query_params.get("scope", "group")))


class TrainMatrixView(APIView):
    """The record of a train (V3-06). Without `equipment` it is the whole
    train; with it, that one machine — the scope list of V3-08."""

    permission_classes = (IsAuthenticated,)

    def get(self, request, group_id: int):
        resolved = resolve_train(request, group_id)
        if resolved is None:
            return Response({"type": "not_found", "status": 404}, status=404)
        return Response(build_matrix(request, *resolved))


def resolve_train(request, group_id: int) -> tuple[Equipment, str] | None:
    """The machine the record is read through, and the scope."""
    machines = _visible(
        request,
        Equipment.objects.for_company(request.company_id)
        .select_related("asset_group__sector__area")
        .filter(asset_group_id=group_id)
        .order_by("order_in_group", "id"),
    )
    wanted = request.query_params.get("equipment")
    if wanted:
        machine = machines.filter(id=wanted).first()
        return (machine, "equipment") if machine else None
    machine = machines.first()
    return (machine, "group") if machine else None


def _equipment(request, equipment_id: int) -> Equipment | None:
    return _visible(
        request,
        Equipment.objects.for_company(request.company_id)
        .select_related("asset_group__sector__area")
        .filter(id=equipment_id),
    ).first()


def _visible(request, machines):
    """What this reader may see: a user narrowed to some areas got every
    train's record by typing its id. Out of reach reads as not found."""
    actor = build_actor(request.user, request.company_id)
    if not actor.has("assets.view_equipment"):
        return machines.none()
    if actor.area_ids is not None:
        machines = machines.filter(asset_group__sector__area_id__in=actor.area_ids)
    return machines


def build_matrix(request, equipment: Equipment, scope: str) -> dict:
    """The payload the screen and the Excel export both read."""
    language = getattr(request, "language", "es")
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
            "image",
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
    techniques: set[int] = set()

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
            # Which visit of this round each machine has: where a value typed
            # into an empty cell of a fixed table is written.
            entry["_visits"][reading.point.equipment_id] = reading.service_visit_id

        magnitude = reading.magnitude
        techniques.add(magnitude.technique_id)
        key = _block_key(reading)
        block = blocks.get(key) or blocks.setdefault(
            key, _new_block(magnitude, reading.unit.code, reading.aggregation, language)
        )
        row_key = _row_key(reading.point, magnitude)
        row = block["rows"].get(row_key) or block["rows"].setdefault(
            row_key, _new_row(reading.point, magnitude)
        )
        existing_cell = row["cells"].get(column_key)
        # A magnitude read once per bearing seeds one row per axis-point
        # (H, V, A) that all collapse into this one row and column. When only
        # one of the three actually carries a value — a thermogram taken on
        # 3H while 3V and 3A are still the seeded "not measured" rows — the
        # iteration order must not let an empty sibling erase the real one.
        if existing_cell is None or existing_cell["value"] is None or reading.value is not None:
            row["cells"][column_key] = {
                "reading_id": reading.id,
                "value": str(reading.value) if reading.value is not None else None,
                "status_code": reading.condition_status.code if reading.condition_status else None,
                "status_color": reading.condition_status.color if reading.condition_status else None,
                # A value no standard judged: shown as "sin norma", not as healthy.
                "graded": reading.condition_status_id is not None or reading.threshold_set_id is not None,
                "quality": reading.quality,
                "visit_id": reading.service_visit_id,
                # A thermogram behind the value (V3-16): the hover thumbnail.
                "image_url": _thumb_url(reading.image) if reading.image_id else None,
            }

    # The fixed tables the train's services measure, even before a round
    # read them: "Aceleración" belongs in the record from the start.
    for point, magnitude in planned_fixed(equipments, techniques):
        key = f"{magnitude.code}:{magnitude.default_aggregation}"
        block = blocks.get(key) or blocks.setdefault(
            key, _new_block(magnitude, magnitude.default_unit.code, magnitude.default_aggregation, language)
        )
        row_key = _row_key(point, magnitude)
        if row_key not in block["rows"]:
            block["rows"][row_key] = _new_row(point, magnitude)

    ordered_columns = sorted(columns.values(), key=lambda column: column["taken_at"])
    return {
        "equipment": {
            "id": equipment.id,
            "name": equipment.name,
            "tag": equipment.client_tag or equipment.asset_code,
            "group": equipment.asset_group.name,
            "area": f"{equipment.asset_group.sector.area.code} - "
                    f"{equipment.asset_group.sector.area.name}",
        },
        "scope": scope,
        "train": _train(equipment),
        "columns": [_public(column) for column in ordered_columns],
        "blocks": [
            {
                **_public(block),
                "rows": sorted(
                    (
                        {
                            **row,
                            "cells": [
                                row["cells"].get(column["key"]) or _open_cell(column, row, block)
                                for column in ordered_columns
                            ],
                        }
                        for row in block["rows"].values()
                    ),
                    key=lambda row: (
                        row["component_order"],
                        row["component_id"],
                        SIDE_ORDER.get(row["side"], 9),
                        row["number"],
                        axis_rank(row["axis"]),
                    ),
                ),
            }
            for block in sorted(
                blocks.values(), key=lambda b: block_sort_key(b["display_order"], b["key"])
            )
        ],
    }


def _new_block(magnitude, unit_code: str, aggregation: str, language: str) -> dict:
    return {
        "key": f"{magnitude.code}:{aggregation}",
        "magnitude_code": magnitude.code,
        "title": magnitude.translated("name", language),
        "unit": unit_code,
        "aggregation": aggregation,
        "decimals": magnitude.decimals,
        # The trend selector has no axis to offer on a magnitude read once
        # per bearing.
        "per_axis": magnitude.per_axis,
        "display_order": magnitude.display_order,
        "_technique_id": magnitude.technique_id,
        "rows": {},
    }


def _row_key(point, magnitude):
    # A magnitude read once on the bearing owns one row per point, not one per
    # axis: the sheet prints "1 ENV", never "1H, 1V, 1A".
    return point.id if magnitude.per_axis else (point.equipment_id, point.number)


def _new_row(point, magnitude) -> dict:
    return {
        "point_id": point.id,
        "label": point.label if magnitude.per_axis else magnitude.row_label(point.number),
        "number": point.number,
        "axis": point.axis,
        "side": point.side,
        "component": point.equipment.name,
        "component_id": point.equipment_id,
        # The train prints in its own order, not in the order the machines
        # happened to be created.
        "component_order": point.equipment.order_in_group,
        "cells": {},
    }


def _open_cell(column: dict, row: dict, block: dict) -> dict | None:
    """An empty cell that can still be filled: a round of this table's service
    with a visit of this machine the user may edit. Saving it creates the
    reading on that visit. Anything else stays a dot."""
    visit_id = column["_visits"].get(row["component_id"])
    if not visit_id or not column["can_edit"] or column["_technique_id"] != block["_technique_id"]:
        return None
    return {
        "reading_id": None,
        "value": None,
        "status_code": None,
        "status_color": None,
        "graded": False,
        "quality": "missing",
        "visit_id": visit_id,
        "image_url": None,
        "point_id": row["point_id"],
        "magnitude_code": block["magnitude_code"],
        "aggregation": block["aggregation"],
    }


def _public(entry: dict) -> dict:
    """What the screen gets: the bookkeeping keys (`_…`) stay here."""
    return {key: value for key, value in entry.items() if not key.startswith("_")}


def _thumb_url(asset) -> str | None:
    from modules.media.infrastructure.local_store import store

    backend = store()
    thumb = (asset.derivatives or {}).get("thumb", {}).get("key")
    return backend.url(thumb) if thumb else backend.url(asset.original_key)


def _train(equipment: Equipment) -> dict:
    """The train and its machines, in the train's order: what the scope list
    offers — the whole train, or each machine by its slot and TAG."""
    group = equipment.asset_group
    return {
        "id": group.id,
        "name": group.name,
        "equipments": [
            {"id": machine.id, "name": machine.name,
             "tag": machine.client_tag or machine.asset_code, "type": machine.equipment_type}
            for machine in group.equipments.order_by("order_in_group", "id")
        ],
    }


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
        "_visits": {},
        "_technique_id": visit.service_order.technique_id if visit else None,
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
