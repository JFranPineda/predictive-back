"""Correctivo work records: what a technician did, when, and who was there.

Open → closed, same shape as a visit: whoever created it edits it while open;
once closed only an administrator can reopen it, and that is audited.
"""

from __future__ import annotations

from datetime import datetime

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.core.infrastructure.audit import record
from modules.maintenance.models import WorkRecord, WorkRecordResponsible
from modules.security.application.access import build_actor

WORK_TYPE_CODES = {code for code, _ in WorkRecord.WORK_TYPES}


class WorkRecordListView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        actor = build_actor(request.user, request.company_id)
        if not actor.has("maintenance.view"):
            raise PermissionDenied("Falta el permiso maintenance.view")

        rows = (
            WorkRecord.objects.for_company(request.company_id)
            .select_related("asset_group", "equipment", "alignment_record")
            .prefetch_related("responsibles__user")
        )
        if actor.area_ids is not None:
            rows = rows.filter(asset_group__sector__area_id__in=actor.area_ids)
        if request.query_params.get("group"):
            rows = rows.filter(asset_group_id=request.query_params["group"])
        if request.query_params.get("work_type"):
            rows = rows.filter(work_types__contains=[request.query_params["work_type"]])
        month = request.query_params.get("month")
        if month:
            year, _, mon = month.partition("-")
            rows = rows.filter(shift_date__year=int(year), shift_date__month=int(mon))

        return Response([_payload(row) for row in rows[:200]])

    def post(self, request):
        actor = build_actor(request.user, request.company_id)
        if not actor.has("maintenance.add_record"):
            raise PermissionDenied("Falta el permiso maintenance.add_record")

        from modules.assets.models import AssetGroup, Equipment

        group = AssetGroup.objects.for_company(request.company_id).filter(
            id=request.data.get("asset_group")
        ).first()
        if group is None:
            raise ValidationError("Debes elegir un conjunto")
        equipment = None
        if request.data.get("equipment"):
            equipment = Equipment.objects.for_company(request.company_id).filter(
                id=request.data["equipment"]
            ).first()

        work_types = _work_types(request.data.get("work_types"))
        started_at = _datetime(request.data.get("started_at"))
        shift_date = (started_at.date() if started_at else timezone.now().date())

        record_row = WorkRecord.objects.create(
            company_id=request.company_id, asset_group=group, equipment=equipment,
            work_types=work_types, other_description=(request.data.get("other_description") or "").strip(),
            started_at=started_at, ended_at=_datetime(request.data.get("ended_at")),
            shift_date=shift_date,
            description=(request.data.get("description") or "").strip(),
            spare_parts_used=(request.data.get("spare_parts_used") or "").strip(),
            client_work_order=(request.data.get("client_work_order") or "").strip(),
            recommendation_id=request.data.get("recommendation") or None,
            alignment_record_id=request.data.get("alignment_record") or None,
            created_by=request.user,
        )
        _set_responsibles(record_row, request.data.get("responsibles"))
        return Response(_payload(record_row), status=201)


class WorkRecordMarkersView(APIView):
    """Closed records on a train, as the trend chart's vertical marks
    (V3-32 AC-05) — dated and labelled, nothing else."""

    permission_classes = (IsAuthenticated,)

    def get(self, request):
        actor = build_actor(request.user, request.company_id)
        if not actor.has("maintenance.view"):
            raise PermissionDenied("Falta el permiso maintenance.view")
        group_id = request.query_params.get("group")
        if not group_id:
            raise ValidationError("Falta el parámetro 'group'")

        rows = WorkRecord.objects.for_company(request.company_id).filter(
            asset_group_id=group_id, is_closed=True
        ).order_by("shift_date", "id")
        return Response([
            {"id": row.id, "date": row.shift_date.isoformat(), "work_types": row.work_types}
            for row in rows
        ])


class WorkRecordDetailView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, record_id: int):
        return Response(_payload(_record(request, record_id)))

    def patch(self, request, record_id: int):
        actor = build_actor(request.user, request.company_id)
        row = _record(request, record_id)

        if request.data.get("reopen"):
            if not actor.has("services.close_visit"):
                raise PermissionDenied("Solo un administrador puede reabrir un registro")
            row.is_closed = False
            row.closed_at = None
            row.closed_by = None
            row.save(update_fields=["is_closed", "closed_at", "closed_by"])
            record(request, "maintenance.reopened", object_type="work_record", object_id=row.id)
            return Response(_payload(row))

        if row.is_closed:
            raise PermissionDenied("Este registro está cerrado")
        if row.created_by_id != request.user.id and not actor.has("maintenance.add_record"):
            raise PermissionDenied("Este registro no es tuyo")

        for field in ("description", "spare_parts_used", "client_work_order", "other_description"):
            if field in request.data:
                setattr(row, field, (request.data.get(field) or "").strip())
        if "work_types" in request.data:
            row.work_types = _work_types(request.data["work_types"])
        if "started_at" in request.data:
            row.started_at = _datetime(request.data["started_at"])
        if "ended_at" in request.data:
            row.ended_at = _datetime(request.data["ended_at"])
        if "equipment" in request.data:
            row.equipment_id = request.data["equipment"] or None
        if "recommendation" in request.data:
            row.recommendation_id = request.data["recommendation"] or None
        if "alignment_record" in request.data:
            row.alignment_record_id = request.data["alignment_record"] or None
        if "responsibles" in request.data:
            _set_responsibles(row, request.data["responsibles"])

        if request.data.get("close"):
            _validate_for_close(row)
            row.is_closed = True
            row.closed_at = timezone.now()
            row.closed_by = request.user
        row.save()
        return Response(_payload(row))


def _validate_for_close(row: WorkRecord) -> None:
    if row.started_at is None:
        raise ValidationError("Falta la hora de inicio")
    if row.ended_at is None:
        raise ValidationError("Falta la hora de fin")
    if row.ended_at <= row.started_at:
        raise ValidationError("La hora de fin debe ser posterior al inicio")
    if not row.work_types:
        raise ValidationError("Elige al menos un tipo de trabajo")
    if "other" in row.work_types and not row.other_description.strip():
        raise ValidationError("Describe el trabajo marcado como 'Otro'")
    if not row.responsibles.exists():
        raise ValidationError("Debes indicar al menos un responsable")


def _work_types(raw) -> list[str]:
    if not raw:
        return []
    codes = raw if isinstance(raw, list) else [raw]
    unknown = set(codes) - WORK_TYPE_CODES
    if unknown:
        raise ValidationError(f"Tipo de trabajo desconocido: {', '.join(unknown)}")
    return codes


def _datetime(raw) -> datetime | None:
    if not raw:
        return None
    value = parse_datetime(raw)
    if value is None:
        raise ValidationError(f"'{raw}' no es una fecha/hora válida")
    return value if timezone.is_aware(value) else timezone.make_aware(value)


def _set_responsibles(row: WorkRecord, raw) -> None:
    if raw is None:
        return
    row.responsibles.all().delete()
    for entry in raw:
        user_id = entry.get("user") if isinstance(entry, dict) else None
        external_name = (entry.get("external_name") or "").strip() if isinstance(entry, dict) else ""
        if not user_id and not external_name:
            continue
        WorkRecordResponsible.objects.create(
            company_id=row.company_id, work_record=row, user_id=user_id or None,
            external_name=external_name,
        )


def _record(request, record_id: int) -> WorkRecord:
    row = (
        WorkRecord.objects.for_company(request.company_id)
        .select_related("asset_group", "equipment")
        .prefetch_related("responsibles__user")
        .filter(id=record_id)
        .first()
    )
    if row is None:
        raise ValidationError("Ese registro no existe")
    return row


def _payload(row: WorkRecord) -> dict:
    return {
        "id": row.id,
        "asset_group": {"id": row.asset_group_id, "name": row.asset_group.name},
        "equipment": (
            {"id": row.equipment_id, "name": row.equipment.name} if row.equipment_id else None
        ),
        "work_types": row.work_types,
        "other_description": row.other_description,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "ended_at": row.ended_at.isoformat() if row.ended_at else None,
        "duration_minutes": row.duration_minutes,
        "shift_date": row.shift_date.isoformat(),
        "description": row.description,
        "spare_parts_used": row.spare_parts_used,
        "client_work_order": row.client_work_order,
        "is_closed": row.is_closed,
        "created_by": row.created_by.get_full_name() if row.created_by else "",
        "recommendation_id": row.recommendation_id,
        "alignment_record_id": row.alignment_record_id,
        "responsibles": [
            {
                "user_id": responsible.user_id,
                "name": responsible.user.get_full_name() if responsible.user else responsible.external_name,
            }
            for responsible in row.responsibles.all()
        ],
    }
