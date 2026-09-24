"""One service visit: what was measured, by whom, and what they wrote.

This is the screen the "Editar mi servicio" link points at. It is the only
place where an external inspector writes, so the ownership rule is enforced on
every write path, not just hidden in the UI.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import transaction
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.diagnostics.models import EquipmentLogEntry
from modules.measurements.models import Reading
from modules.security.application.access import build_actor
from modules.security.domain.policies import VisitRef, can_edit_visit, can_write_log_entry
from modules.services.models import ServiceVisit


def _reference(visit: ServiceVisit) -> VisitRef:
    participants = list(visit.participants.all())
    return VisitRef(
        id=visit.id,
        area_id=visit.equipment.asset_group.sector.area_id,
        participant_ids=frozenset(p.user_id for p in participants),
        lead_analyst_id=next((p.user_id for p in participants if p.role == "lead_analyst"), None),
        is_closed=visit.is_closed,
        report_issued=False,
        visited_on=visit.visited_at.date(),
    )


def _load(request, visit_id: int) -> ServiceVisit:
    return (
        ServiceVisit.objects.for_company(request.company_id)
        .select_related(
            "equipment__asset_group__sector__area",
            "service_order__technique",
            "availability_status",
            "instrument",
        )
        .prefetch_related("participants__user", "fault_modes")
        .get(id=visit_id)
    )


class VisitDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, visit_id: int):
        language = getattr(request, "language", "es")
        visit = _load(request, visit_id)
        actor = build_actor(request.user, request.company_id)
        reference = _reference(visit)
        equipment = visit.equipment
        area = equipment.asset_group.sector.area

        readings = (
            Reading.objects.for_company(request.company_id)
            .filter(service_visit=visit)
            .select_related("point", "magnitude", "unit", "condition_status")
            .order_by("point__number", "point__axis", "magnitude__code")
        )

        points: dict[int, dict] = {}
        for reading in readings:
            point = points.setdefault(reading.point_id, {
                "point_id": reading.point_id,
                "label": reading.point.label,
                "number": reading.point.number,
                "axis": reading.point.axis,
                "side": reading.point.side,
                "values": [],
            })
            point["values"].append({
                "reading_id": reading.id,
                "magnitude_code": reading.magnitude.code,
                "magnitude_name": reading.magnitude.translated("name", language),
                "value": str(reading.value) if reading.value is not None else None,
                "unit": reading.unit.code,
                "decimals": reading.magnitude.decimals,
                "aggregation": reading.aggregation,
                "status": _status(reading.condition_status, language),
                "quality": reading.quality,
                "not_measured_reason": reading.not_measured_reason or None,
            })

        entries = (
            EquipmentLogEntry.objects.for_company(request.company_id)
            .filter(equipment=equipment)
            .select_related("author")
            .order_by("entry_date", "id")
        )

        return Response({
            "visit_id": visit.id,
            "equipment": {
                "id": equipment.id,
                "name": equipment.name,
                "tag": equipment.client_tag or equipment.asset_code,
                "type": equipment.equipment_type,
                "asset_group": equipment.asset_group.name,
                "area_label": f"{area.code} - {area.name}",
                "sector": equipment.asset_group.sector.name,
            },
            "service_order": {
                "code": visit.service_order.code,
                "client_work_order": visit.service_order.client_work_order,
            },
            "technique_code": visit.service_order.technique.code,
            "technique_name": visit.service_order.technique.translated("name", language),
            "visited_at": visit.visited_at.isoformat(),
            "instrument": visit.instrument.name if visit.instrument else None,
            "availability_status": _status(visit.availability_status, language),
            "participants": [
                {
                    "user_id": p.user_id, "full_name": p.user.get_full_name(),
                    "initials": p.user.initials, "role": p.role,
                    "is_external": p.user.is_external,
                }
                for p in visit.participants.all()
            ],
            "points": sorted(points.values(), key=lambda p: (p["number"], p["axis"])),
            "entries": [
                {
                    "id": entry.id,
                    "entry_type": entry.entry_type,
                    "entry_date": entry.entry_date.isoformat(),
                    "text": entry.text,
                    "author_id": entry.author_id,
                    "author_name": entry.author.get_full_name() if entry.author else "",
                    "status": entry.status or None,
                    "from_this_visit": entry.service_visit_id == visit.id,
                }
                for entry in entries
            ],
            "fault_modes": [
                {"code": fault.code, "name": fault.translated("name", language),
                 "reference": fault.iso_reference}
                for fault in visit.fault_modes.all()
            ],
            "is_closed": visit.is_closed,
            "report_issued": False,
            "can_edit": can_edit_visit(actor, reference),
        })


class VisitReadingsView(APIView):
    """Saves the values the inspector typed. Ownership is checked here, not in
    the browser: hiding a button is not authorization."""

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, visit_id: int):
        visit = _load(request, visit_id)
        actor = build_actor(request.user, request.company_id)
        if not can_edit_visit(actor, _reference(visit)):
            raise PermissionDenied("Esta visita no es tuya o ya está cerrada")

        updates = {int(row["reading_id"]): row.get("value") for row in request.data.get("readings", [])}
        readings = list(
            Reading.objects.for_company(request.company_id)
            .filter(service_visit=visit, id__in=updates)
            .select_related(
                "magnitude",
                "point__equipment__nameplate",
                "point__equipment__applied_standard",
                "point__equipment__machine_class",
                "point__equipment__asset_group__kind",
            )
        )
        from modules.core.infrastructure.audit import record

        saved = 0
        for reading in readings:
            raw = updates[reading.id]
            before = {
                "value": None if reading.value is None else str(reading.value),
                "status": reading.condition_status.code if reading.condition_status else None,
            }
            reading.value = _decimal(raw)
            reading.quality = "ok" if reading.value is not None else "not_measured"
            reading.condition_status = _evaluate(request.company_id, reading)
            # `operator` is who took the measurement and stays so. Overwriting
            # it with whoever corrected the value erased the technician the
            # managers' board is meant to show; the correction is recorded in
            # the audit trail instead, with its own author.
            reading.save(update_fields=["value", "quality", "condition_status", "updated_at"])
            after = {
                "value": None if reading.value is None else str(reading.value),
                "status": reading.condition_status.code if reading.condition_status else None,
            }
            if after != before:
                record(request, "reading.corrected", object_type="reading",
                       object_id=reading.id, before=before, after=after)
            saved += 1
        return Response({"saved": saved})


class VisitEntriesView(APIView):
    """Notes, observations, conclusions and recommendations."""

    permission_classes = [IsAuthenticated]

    def post(self, request, visit_id: int):
        visit = _load(request, visit_id)
        actor = build_actor(request.user, request.company_id)
        if not can_write_log_entry(actor, _reference(visit)):
            raise PermissionDenied("Esta visita no es tuya o ya está cerrada")

        entry = EquipmentLogEntry.objects.create(
            company_id=request.company_id,
            equipment=visit.equipment,
            service_visit=visit,
            entry_type=request.data.get("entry_type", "note"),
            entry_date=visit.visited_at.date(),
            text=(request.data.get("text") or "").strip(),
            author=request.user,
            status="open" if request.data.get("entry_type") == "recommendation" else "",
        )
        return Response({
            "id": entry.id, "entry_type": entry.entry_type,
            "entry_date": entry.entry_date.isoformat(), "text": entry.text,
            "author_id": entry.author_id, "author_name": request.user.get_full_name(),
            "status": entry.status or None, "from_this_visit": True,
        }, status=201)


def _status(row, language: str) -> dict | None:
    if row is None:
        return None
    return {
        "code": row.code, "name": row.translated("name", language),
        "color": row.color, "kind": row.kind, "severity": row.severity,
        "measurable": row.measurable,
    }


def _decimal(raw) -> Decimal | None:
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw).replace(",", "."))
    except InvalidOperation:
        return None


def _evaluate(company_id: int, reading: Reading):
    """Re-runs the cascade for the value just typed, so the status the
    inspector sees is the one the system will report."""
    from modules.thresholds.application.evaluation import context_for
    from modules.thresholds.domain.services import evaluate, resolve
    from modules.thresholds.infrastructure.models import Status
    from modules.thresholds.infrastructure.repositories import DjangoThresholdRepository

    if reading.value is None:
        return None
    candidates = DjangoThresholdRepository().candidates(company_id, reading.magnitude.code)
    context = context_for(
        reading.point.equipment, reading.magnitude.code, reading.aggregation, reading.point_id
    )
    verdict = evaluate(reading.value, resolve(candidates, context, reading.taken_at.date()))
    if verdict.status is None:
        return None
    return Status.objects.filter(company_id=company_id, code=verdict.status.code).first()
