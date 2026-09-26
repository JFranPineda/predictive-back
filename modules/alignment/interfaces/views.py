"""Alineamiento: one record per laser job, before and after, judged against
the tolerance its own RPM asked for.

Ownership follows the visit when there is one, exactly like a reading: an
external inspector may only touch the job he came to do, and only while it is
open. A record with no visit (created directly from Mediciones → Alineamiento
for a train's history) only needs `alignment.manage`.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db.models import F, Q
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.alignment.domain.tolerances import (
    AxisValues,
    Tolerance,
    default_tolerance_for,
    evaluate,
)
from modules.alignment.infrastructure.models import AlignmentRecord, AlignmentTolerance
from modules.assets.models import AssetGroup
from modules.media.infrastructure.uploads import UploadRejectedError, store_upload
from modules.security.application.access import build_actor
from modules.security.domain.policies import can_edit_visit
from modules.services.infrastructure.visit_refs import visit_ref

PHASES = ("angular_h", "parallel_h", "angular_v", "parallel_v")
# The 3 "representative" photos (1 of the train, up to 2 of the finding) plus
# the tool's own before/after screens, one shot each.
PHOTO_LIMITS = {
    "alignment_group": 1,
    "alignment_observation": 2,
    "alignment_before": 1,
    "alignment_after": 1,
}


class AlignmentRecordListView(APIView):
    """`GET` — Mediciones → Alineamiento: what was aligned, filterable by
    month and train. `POST` — a new record."""

    permission_classes = (IsAuthenticated,)

    def get(self, request):
        actor = build_actor(request.user, request.company_id)
        if not actor.has("alignment.view"):
            raise PermissionDenied("Falta el permiso alignment.view")

        rows = (
            AlignmentRecord.objects.for_company(request.company_id)
            .select_related("asset_group__sector__area", "service_visit", "diagnosed_fault")
        )
        if actor.area_ids is not None:
            rows = rows.filter(asset_group__sector__area_id__in=actor.area_ids)
        month = request.query_params.get("month")
        if month:
            year, _, mon = month.partition("-")
            rows = rows.filter(created_at__year=int(year), created_at__month=int(mon))
        if request.query_params.get("group"):
            rows = rows.filter(asset_group_id=request.query_params["group"])
        if request.query_params.get("service_visit"):
            rows = rows.filter(service_visit_id=request.query_params["service_visit"])

        return Response([_payload(request, row) for row in rows[:200]])

    def post(self, request):
        actor = build_actor(request.user, request.company_id)
        if not actor.has("alignment.manage"):
            raise PermissionDenied("Falta el permiso alignment.manage")

        group = AssetGroup.objects.for_company(request.company_id).filter(
            id=request.data.get("asset_group")
        ).first()
        if group is None:
            raise ValidationError("Debes elegir un conjunto")

        visit = _visit_or_none(request, request.data.get("service_visit"))
        if visit is not None and not can_edit_visit(actor, visit_ref(visit)):
            raise PermissionDenied("Esta visita no es tuya o ya está cerrada")

        rpm = _decimal(request.data.get("rpm"))
        if rpm is None:
            raise ValidationError("El RPM es obligatorio: la tolerancia depende de él")
        tolerance = _tolerance_for(request.company_id, group, rpm)

        record = AlignmentRecord.objects.create(
            company_id=request.company_id, asset_group=group, service_visit=visit,
            driver_label=(request.data.get("driver_label") or "").strip(),
            driven_label=(request.data.get("driven_label") or "").strip(),
            rpm=rpm, instrument=(request.data.get("instrument") or "").strip(),
            backlash_within_tolerance=_bool_or_none(request.data.get("backlash_within_tolerance")),
            notes=(request.data.get("notes") or "").strip(),
            tolerance_parallel_mm=tolerance.parallel_mm,
            tolerance_angular_mm_per_100mm=tolerance.angular_mm_per_100mm,
            diagnosed_fault_id=request.data.get("diagnosed_fault") or None,
            created_by=request.user,
            **_phase_fields("before", request.data),
            **_phase_fields("after", request.data),
        )
        return Response(_payload(request, record), status=201)


class AlignmentRecordDetailView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, record_id: int):
        record = _record(request, record_id)
        return Response(_payload(request, record))

    def patch(self, request, record_id: int):
        record = _writable_record(request, record_id)
        for field in ("driver_label", "driven_label", "instrument", "notes"):
            if field in request.data:
                setattr(record, field, (request.data.get(field) or "").strip())
        if "backlash_within_tolerance" in request.data:
            record.backlash_within_tolerance = _bool_or_none(
                request.data["backlash_within_tolerance"]
            )
        if "diagnosed_fault" in request.data:
            record.diagnosed_fault_id = request.data["diagnosed_fault"] or None
        if "rpm" in request.data:
            rpm = _decimal(request.data["rpm"])
            if rpm is not None:
                record.rpm = rpm
                # The tolerance is re-frozen only when the speed itself
                # changes — editing a photo caption must never reopen a
                # verdict the customer already read (AC-05).
                tolerance = _tolerance_for(request.company_id, record.asset_group, rpm)
                record.tolerance_parallel_mm = tolerance.parallel_mm
                record.tolerance_angular_mm_per_100mm = tolerance.angular_mm_per_100mm
        for phase in ("before", "after"):
            for field, value in _phase_fields(phase, request.data).items():
                setattr(record, field, value)
        record.save()
        return Response(_payload(request, record))

    def delete(self, request, record_id: int):
        record = _writable_record(request, record_id)
        record.delete()
        return Response(status=204)


class AlignmentPhotoView(APIView):
    """One of the four fixed roles, with the cap V3-17 asks for enforced here
    — the generic media endpoint has no idea what "3 representative photos"
    means for this record."""

    permission_classes = (IsAuthenticated,)
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, record_id: int):
        record = _writable_record(request, record_id)
        kind = request.data.get("kind")
        if kind not in PHOTO_LIMITS:
            raise ValidationError(f"Rol de foto desconocido: {kind}")

        from modules.media.infrastructure.models import MediaAsset

        existing = MediaAsset.objects.for_company(request.company_id).filter(
            owner_type="alignment_record", owner_id=record.id, kind=kind
        ).count()
        if existing >= PHOTO_LIMITS[kind]:
            raise ValidationError(
                f"Ya hay {existing} foto(s) de tipo '{kind}'; el máximo es {PHOTO_LIMITS[kind]}"
            )

        try:
            asset, _created = store_upload(
                company_id=request.company_id, upload=request.FILES.get("file"), kind=kind,
                owner_type="alignment_record", owner_id=record.id,
                caption=(request.data.get("caption") or "").strip(), user=request.user,
            )
        except UploadRejectedError as cause:
            raise ValidationError(str(cause)) from cause
        return Response({"id": asset.id, "kind": asset.kind, "caption": asset.caption}, status=201)


def _writable_record(request, record_id: int) -> AlignmentRecord:
    record = _record(request, record_id)
    actor = build_actor(request.user, request.company_id)
    if record.service_visit_id and not can_edit_visit(actor, visit_ref(record.service_visit)):
        raise PermissionDenied("Esta visita no es tuya o ya está cerrada")
    if not record.service_visit_id and not actor.has("alignment.manage"):
        raise PermissionDenied("Falta el permiso alignment.manage")
    return record


def _record(request, record_id: int) -> AlignmentRecord:
    record = (
        AlignmentRecord.objects.for_company(request.company_id)
        .select_related("asset_group", "service_visit")
        .filter(id=record_id)
        .first()
    )
    if record is None:
        raise ValidationError("Ese registro de alineamiento no existe")
    return record


def _visit_or_none(request, visit_id):
    if not visit_id:
        return None
    from modules.services.infrastructure.models import ServiceVisit

    visit = ServiceVisit.objects.for_company(request.company_id).filter(id=visit_id).first()
    if visit is None:
        raise ValidationError("Esa visita no existe")
    return visit


def _tolerance_for(company_id: int, group: AssetGroup, rpm: Decimal) -> Tolerance:
    """The train's own override tier if one covers this RPM; the global chart
    otherwise. Never raises: a chart with no tier for an unusual speed still
    returns the strictest tier, which is the safe direction to guess wrong."""
    override = (
        AlignmentTolerance.objects.for_company(company_id)
        .filter(Q(asset_group=group) | Q(asset_group__isnull=True))
        .order_by(F("asset_group_id").asc(nulls_last=True), F("rpm_ceiling").asc(nulls_last=True))
    )
    for row in override:
        if row.rpm_ceiling is None or float(rpm) < row.rpm_ceiling:
            return Tolerance(row.parallel_mm, row.angular_mm_per_100mm)
    return default_tolerance_for(rpm)


def _phase_fields(phase: str, data) -> dict:
    return {
        f"{phase}_{axis}": _decimal(data.get(f"{phase}_{axis}"))
        for axis in PHASES
        if f"{phase}_{axis}" in data
    }


def _payload(request, record: AlignmentRecord) -> dict:
    tolerance = Tolerance(record.tolerance_parallel_mm, record.tolerance_angular_mm_per_100mm)
    before = AxisValues(
        record.before_angular_h, record.before_parallel_h,
        record.before_angular_v, record.before_parallel_v,
    )
    after = AxisValues(
        record.after_angular_h, record.after_parallel_h,
        record.after_angular_v, record.after_parallel_v,
    )
    before_verdict = evaluate(before, tolerance)
    after_verdict = evaluate(after, tolerance)

    from modules.media.infrastructure.local_store import store
    from modules.media.infrastructure.models import MediaAsset

    backend = store()
    photos = (
        MediaAsset.objects.for_company(request.company_id)
        .filter(owner_type="alignment_record", owner_id=record.id)
        .order_by("kind", "-created_at")
    )
    return {
        "id": record.id,
        "asset_group": {"id": record.asset_group_id, "name": record.asset_group.name},
        "service_visit_id": record.service_visit_id,
        "driver_label": record.driver_label,
        "driven_label": record.driven_label,
        "rpm": str(record.rpm),
        "instrument": record.instrument,
        "backlash_within_tolerance": record.backlash_within_tolerance,
        "notes": record.notes,
        "created_at": record.created_at.isoformat(),
        "created_by": record.created_by.get_full_name() if record.created_by else "",
        "tolerance": {
            "parallel_mm": str(record.tolerance_parallel_mm),
            "angular_mm_per_100mm": str(record.tolerance_angular_mm_per_100mm),
        },
        "before": _phase_payload(before, before_verdict),
        "after": _phase_payload(after, after_verdict),
        "all_ok": after_verdict.all_ok,
        "photos": [
            {
                "id": photo.id, "kind": photo.kind, "caption": photo.caption,
                "url": backend.url(photo.original_key),
                "thumb_url": backend.url((photo.derivatives or {}).get("thumb", {}).get("key"))
                if (photo.derivatives or {}).get("thumb") else None,
            }
            for photo in photos
        ],
    }


def _phase_payload(values: AxisValues, verdict) -> dict:
    return {
        axis: {
            "value": str(getattr(values, axis)) if getattr(values, axis) is not None else None,
            "ok": getattr(verdict, axis),
        }
        for axis in PHASES
    }


def _decimal(raw) -> Decimal | None:
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw).replace(",", "."))
    except InvalidOperation as cause:
        raise ValidationError(f"'{raw}' no es un número") from cause


def _bool_or_none(raw):
    if raw in (None, ""):
        return None
    if isinstance(raw, bool):
        return raw
    return str(raw).lower() in ("1", "true", "yes", "si", "sí")
