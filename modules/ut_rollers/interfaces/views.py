"""UT en rodillos: the order's grid of rollers, filled in one sheet.

A roller is an ordinary equipment with six points, and its thicknesses are
ordinary readings of an ordinary visit — one visit per roller and order, the
same ownership and lock rules as any round. The sheet only saves them all in
one go and reads them back as the customer's order prints them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.core.infrastructure.audit import record
from modules.core.infrastructure.bus import bus
from modules.core.infrastructure.transactions import tenant_atomic
from modules.measurements.application.record_readings import ReadingInput, RecordReadings
from modules.measurements.infrastructure.repositories import DjangoPointContextRepository
from modules.media.infrastructure.refs import image_ref
from modules.thresholds.infrastructure.repositories import DjangoThresholdRepository
from modules.ut_rollers.domain.rollers import (
    LABELS,
    MAGNITUDE,
    POINTS,
    SIDES,
    TECHNIQUE,
    describe_indication,
    headline,
    state_of,
    tally,
)
from modules.ut_rollers.infrastructure.readings import ReplacingReadingRepository
from modules.ut_rollers.interfaces.common import find_order, lock_of, require, rollers_of, visit_for
from modules.ut_rollers.models import UTIndication


class RollerSheetView(APIView):
    """`GET|POST ut-rollers/orders/<id>/sheet/?group=<id>` — one row per roller."""

    permission_classes = (IsAuthenticated,)

    def get(self, request, order_id: int):
        require(request, "ut_rollers.view")
        order = find_order(request, order_id)
        group_id = request.query_params.get("group")
        if not group_id:
            raise ValidationError("Falta el parámetro 'group'")
        return Response(_sheet(request, order, int(group_id)))

    @tenant_atomic
    def post(self, request, order_id: int):
        actor = require(request, "ut_rollers.capture")
        if not actor.has("measurements.add_reading"):
            raise PermissionDenied("Falta el permiso measurements.add_reading")
        order = find_order(request, order_id)
        group_id = int(request.data.get("group") or 0)
        rows = request.data.get("rows") or []
        if not rows:
            raise ValidationError("No llegó ningún rodillo")

        rollers = {row.id: row for row in rollers_of(request, group_id)}
        use_case = RecordReadings(
            readings_repo=ReplacingReadingRepository(),
            thresholds_repo=DjangoThresholdRepository(getattr(request, "language", "es")),
            points_repo=DjangoPointContextRepository(),
            events=bus,
        )
        saved = 0
        for row in rows:
            roller = rollers.get(int(row.get("equipment") or 0))
            if roller is None:
                raise ValidationError("Un rodillo no pertenece a ese conjunto")
            values = _values(row.get("values") or [])
            inaccessible = bool(row.get("inaccessible"))
            observation = (row.get("observation") or "").strip()
            if not inaccessible and all(value is None for value in values) and not observation:
                continue
            visit = visit_for(request, actor, order, roller)
            points = {point.number: point.id for point in roller.points.all()}
            inputs = tuple(
                ReadingInput(
                    point_id=points[number],
                    magnitude_code=MAGNITUDE,
                    value=None if inaccessible else value,
                    unit_code="mm",
                    aggregation="min",
                    quality="not_measured" if inaccessible or value is None else "ok",
                    not_measured_reason="no_access" if inaccessible else "",
                )
                for number, value in zip(range(1, POINTS + 1), values, strict=True)
                if number in points and (inaccessible or value is not None)
            )
            if inputs:
                use_case.execute(
                    company_id=request.company_id,
                    service_visit_id=visit.id,
                    taken_at=visit.visited_at or datetime.now(UTC),
                    inputs=inputs,
                    operator_id=request.user.id,
                    standard_code=order.standard.code if order.standard_id else None,
                )
            _save_observation(request, visit, observation)
            saved += 1

        record(
            request,
            "reading.captured",
            object_type="service_order",
            object_id=order.id,
            after={"technique": TECHNIQUE, "rollers": saved},
        )
        return Response(_sheet(request, order, group_id), status=201)


class IndicationListView(APIView):
    """`GET ut-rollers/indications/?equipment=<id>&order=<id>&side=`, `POST`
    a new one. A journal finding (Q15) names its side and its order; it is
    filed under that order's visit of the roller."""

    permission_classes = (IsAuthenticated,)

    def get(self, request):
        require(request, "ut_rollers.view")
        rows = UTIndication.objects.for_company(request.company_id)
        if request.query_params.get("equipment"):
            rows = rows.filter(equipment_id=request.query_params["equipment"])
        if request.query_params.get("group"):
            rows = rows.filter(equipment__asset_group_id=request.query_params["group"])
        if request.query_params.get("order"):
            rows = rows.filter(service_visit__service_order_id=request.query_params["order"])
        if request.query_params.get("side"):
            rows = rows.filter(side=request.query_params["side"])
        return Response([_indication(row) for row in rows.select_related("equipment")[:500]])

    def post(self, request):
        actor = require(request, "ut_rollers.capture")
        from modules.assets.models import Equipment

        roller = (
            Equipment.objects.for_company(request.company_id)
            .filter(id=request.data.get("equipment"), equipment_type="roller")
            .first()
        )
        if roller is None:
            raise ValidationError("Ese rodillo no existe")
        kind = request.data.get("kind")
        if kind not in dict(UTIndication.KINDS):
            raise ValidationError("Tipo de incidencia desconocido")
        side = request.data.get("side") or ""
        if side and side not in SIDES:
            raise ValidationError("Lado desconocido: mando o transmisión")
        visit_id = request.data.get("service_visit") or None
        if request.data.get("service_order"):
            visit_id = visit_for(
                request, actor, find_order(request, request.data["service_order"]), roller
            ).id
        row = UTIndication.objects.create(
            company_id=request.company_id,
            equipment=roller,
            kind=kind,
            side=side,
            service_visit_id=visit_id,
            length_mm=_decimal(request.data.get("length_mm")),
            depth_mm=_decimal(request.data.get("depth_mm")),
            position=(request.data.get("position") or "").strip(),
            notes=(request.data.get("notes") or "").strip(),
            created_by=request.user,
        )
        return Response(_indication(row), status=201)


class IndicationDetailView(APIView):
    permission_classes = (IsAuthenticated,)

    def patch(self, request, indication_id: int):
        require(request, "ut_rollers.capture")
        row = _find_indication(request, indication_id)
        if "kind" in request.data:
            if request.data["kind"] not in dict(UTIndication.KINDS):
                raise ValidationError("Tipo de incidencia desconocido")
            row.kind = request.data["kind"]
        for field in ("length_mm", "depth_mm"):
            if field in request.data:
                setattr(row, field, _decimal(request.data[field]))
        for field in ("position", "notes"):
            if field in request.data:
                setattr(row, field, (request.data[field] or "").strip())
        row.save()
        return Response(_indication(row))

    def delete(self, request, indication_id: int):
        require(request, "ut_rollers.capture")
        row = _find_indication(request, indication_id)
        record(request, "ut_rollers.indication_deleted", object_type="ut_indication", object_id=row.id)
        row.delete()
        return Response(status=204)


def _save_observation(request, visit, text: str) -> None:
    from modules.diagnostics.models import EquipmentLogEntry

    entry = (
        EquipmentLogEntry.objects.for_company(request.company_id)
        .filter(service_visit=visit, entry_type="observation")
        .order_by("id")
        .first()
    )
    if entry is None and text:
        EquipmentLogEntry.objects.create(
            company_id=request.company_id,
            equipment=visit.equipment,
            service_visit=visit,
            entry_type="observation",
            entry_date=visit.visited_at.date(),
            text=text,
            author=request.user,
        )
    elif entry is not None and entry.text != text:
        if text:
            entry.text = text
            entry.save(update_fields=["text"])
        else:
            entry.delete()


def _sheet(request, order, group_id: int) -> dict:
    from modules.diagnostics.models import EquipmentLogEntry
    from modules.measurements.models import Reading
    from modules.services.models import ServiceVisit

    rollers = rollers_of(request, group_id)
    visits = {
        visit.equipment_id: visit
        for visit in ServiceVisit.objects.for_company(request.company_id)
        .filter(service_order=order, equipment__in=rollers)
        .order_by("visited_at", "id")
    }
    readings: dict[int, dict[int, Reading]] = {}
    for reading in (
        Reading.objects.for_company(request.company_id)
        .filter(service_visit__in=visits.values(), magnitude__code=MAGNITUDE)
        .select_related("point", "condition_status")
        .order_by("id")
    ):
        readings.setdefault(reading.service_visit_id, {})[reading.point.number] = reading
    notes = {
        entry.service_visit_id: entry.text
        for entry in EquipmentLogEntry.objects.for_company(request.company_id)
        .filter(service_visit__in=visits.values(), entry_type="observation")
        .order_by("id")
    }
    indications: dict[int, int] = {}
    for equipment_id in (
        UTIndication.objects.for_company(request.company_id)
        .filter(equipment__in=rollers)
        .values_list("equipment_id", flat=True)
    ):
        indications[equipment_id] = indications.get(equipment_id, 0) + 1

    rows = []
    for roller in rollers:
        visit = visits.get(roller.id)
        by_point = readings.get(visit.id, {}) if visit else {}
        values = [by_point.get(number) for number in range(1, POINTS + 1)]
        inaccessible = bool(by_point) and all(
            r is not None and r.value is None and r.not_measured_reason == "no_access" for r in values
        )
        worst = max(
            (r.condition_status for r in values if r is not None and r.condition_status is not None),
            key=lambda status: status.severity,
            default=None,
        )
        state = state_of(inaccessible=inaccessible, status_code=worst.code if worst else None)
        thinnest = headline(r.value for r in values if r is not None)
        rows.append(
            {
                "equipment_id": roller.id,
                "number": roller.order_in_group,
                "name": roller.name,
                "visit_id": visit.id if visit else None,
                "is_closed": bool(visit and visit.is_closed),
                "values": [None if r is None or r.value is None else str(r.value) for r in values],
                "min": None if thinnest is None else str(thinnest),
                "inaccessible": inaccessible,
                "state": state,
                "status": None
                if worst is None
                else {
                    "code": worst.code,
                    "label": LABELS.get(worst.code, worst.name),
                    "color": worst.color,
                },
                "observation": notes.get(visit.id, "") if visit else "",
                "indications": indications.get(roller.id, 0),
            }
        )
    return {
        "order": {"id": order.id, "code": order.code},
        "group_id": group_id,
        "rows": rows,
        "summary": tally(row["state"] for row in rows),
        "lock_reason": lock_of(request, order, group_id),
    }


def _values(raw: list) -> list[Decimal | None]:
    values = [_decimal(value) for value in list(raw)[:POINTS]]
    return values + [None] * (POINTS - len(values))


def _decimal(raw) -> Decimal | None:
    if raw in (None, ""):
        return None
    try:
        value = Decimal(str(raw).replace(",", "."))
    except InvalidOperation as cause:
        raise ValidationError(f"'{raw}' no es un número") from cause
    if value < 0:
        raise ValidationError("Un espesor no puede ser negativo")
    return value


def _find_indication(request, indication_id: int) -> UTIndication:
    row = UTIndication.objects.for_company(request.company_id).filter(id=indication_id).first()
    if row is None:
        raise ValidationError("Esa incidencia no existe")
    return row


def _indication(row: UTIndication) -> dict:
    from modules.media.infrastructure.models import MediaAsset

    photos = MediaAsset.objects.for_company(row.company_id).filter(
        owner_type="ut_indication", owner_id=row.id
    )
    return {
        "id": row.id,
        "equipment_id": row.equipment_id,
        "service_visit_id": row.service_visit_id,
        "kind": row.kind,
        "side": row.side,
        "description": describe_indication(row.kind, row.length_mm, row.depth_mm, row.notes),
        "length_mm": None if row.length_mm is None else str(row.length_mm),
        "depth_mm": None if row.depth_mm is None else str(row.depth_mm),
        "position": row.position,
        "notes": row.notes,
        "created_at": row.created_at.isoformat(),
        "photos": [image_ref(photo) for photo in photos],
    }
