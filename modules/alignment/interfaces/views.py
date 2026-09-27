"""Alineamiento: one record per laser job, before and after, judged against
the tolerance its own RPM asked for.

Ownership follows the visit when there is one, exactly like a reading: an
external inspector may only touch the job he came to do, and only while it is
open. A record with no visit (created directly from Mediciones → Alineamiento
for a train's history) only needs `alignment.manage`.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.alignment.domain.tolerances import (
    AxisValues,
    Band,
    InvalidTiersError,
    Tolerance,
    acceptance,
    check_bands,
    check_tiers,
    default_tolerance_for,
    evaluate,
    kind_of,
    state_of,
    worst,
)
from modules.alignment.infrastructure.models import AlignmentRecord, AlignmentTolerance
from modules.alignment.infrastructure.scales import bands_from, labels, scale_for, snapshot_of, tiers_of
from modules.assets.models import AssetGroup
from modules.core.infrastructure import audit
from modules.core.infrastructure.transactions import tenant_atomic
from modules.media.infrastructure.uploads import UploadRejectedError, store_upload
from modules.security.application.access import build_actor
from modules.security.domain.policies import can_edit_visit
from modules.services.infrastructure.visit_refs import visit_ref

PHASES = ("angular_h", "parallel_h", "angular_v", "parallel_v")
ALIGNERS = dict(AlignmentRecord.ALIGNERS)


def photo_limits(aligner: str) -> dict[str, int]:
    """The train's images (Q10): 1 of the train, up to 2 of the finding, and
    the aligner's own result — one screen with before and after for SKF, one
    screen per phase for any other aligner."""
    limits = {"alignment_group": 1, "alignment_observation": 2}
    if aligner == "skf":
        limits["alignment_result"] = 1
    else:
        limits.update(alignment_before=1, alignment_after=1)
    return limits


class AlignmentRecordListView(APIView):
    """`GET` — Mediciones → Alineamiento: what was aligned, filterable by
    month and train. `POST` — a new record."""

    permission_classes = (IsAuthenticated,)

    def get(self, request):
        actor = build_actor(request.user, request.company_id)
        if not actor.has("alignment.view"):
            raise PermissionDenied("Falta el permiso alignment.view")

        rows = AlignmentRecord.objects.for_company(request.company_id).select_related(
            "asset_group__sector__area", "service_visit", "diagnosed_fault"
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

        group = (
            AssetGroup.objects.for_company(request.company_id)
            .filter(id=request.data.get("asset_group"))
            .first()
        )
        if group is None:
            raise ValidationError("Debes elegir un conjunto")

        visit = _visit_or_none(request, request.data.get("service_visit"))
        if visit is not None and not can_edit_visit(actor, visit_ref(visit)):
            raise PermissionDenied("Esta visita no es tuya o ya está cerrada")

        rpm = _decimal(request.data.get("rpm"))
        if rpm is None:
            raise ValidationError("El RPM es obligatorio: la tolerancia depende de él")
        standard = _standard(request, request.data.get("standard"))
        bands, tolerance = _frozen(request, group, rpm, standard)

        record = AlignmentRecord.objects.create(
            company_id=request.company_id,
            asset_group=group,
            service_visit=visit,
            driver_label=(request.data.get("driver_label") or "").strip(),
            driven_label=(request.data.get("driven_label") or "").strip(),
            rpm=rpm,
            instrument=(request.data.get("instrument") or "").strip(),
            aligner=_aligner(request.data.get("aligner") or "skf"),
            backlash_within_tolerance=_bool_or_none(request.data.get("backlash_within_tolerance")),
            notes=(request.data.get("notes") or "").strip(),
            tolerance_parallel_mm=tolerance.parallel_mm,
            tolerance_angular_mm_per_100mm=tolerance.angular_mm_per_100mm,
            scale_snapshot=snapshot_of(bands),
            standard=standard,
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
            record.backlash_within_tolerance = _bool_or_none(request.data["backlash_within_tolerance"])
        if "diagnosed_fault" in request.data:
            record.diagnosed_fault_id = request.data["diagnosed_fault"] or None
        if "aligner" in request.data:
            record.aligner = _aligner(request.data["aligner"])
        rpm = _decimal(request.data.get("rpm")) if "rpm" in request.data else None
        if "standard" in request.data:
            record.standard = _standard(request, request.data["standard"])
        if rpm is not None or "standard" in request.data:
            record.rpm = rpm if rpm is not None else record.rpm
            # The tolerance is re-frozen only when the speed or the norma
            # changes — editing a photo caption must never reopen a verdict
            # the customer already read (AC-05).
            bands, tolerance = _frozen(request, record.asset_group, record.rpm, record.standard)
            record.tolerance_parallel_mm = tolerance.parallel_mm
            record.tolerance_angular_mm_per_100mm = tolerance.angular_mm_per_100mm
            record.scale_snapshot = snapshot_of(bands)
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
    """One of the train's fixed image roles, with its cap enforced here — the
    generic media endpoint has no idea which screens this aligner prints.
    `DELETE …/photos/<id>/` takes one back while the record is editable."""

    permission_classes = (IsAuthenticated,)
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, record_id: int):
        record = _writable_record(request, record_id)
        kind = request.data.get("kind")
        limits = photo_limits(record.aligner)
        if kind not in limits:
            expected = (
                "una sola imagen de resultado"
                if record.aligner == "skf"
                else "una imagen antes y otra después"
            )
            raise ValidationError(f"{ALIGNERS[record.aligner]}: el conjunto lleva {expected}")

        from modules.media.infrastructure.models import MediaAsset

        existing = (
            MediaAsset.objects.for_company(request.company_id)
            .filter(owner_type="alignment_record", owner_id=record.id, kind=kind)
            .count()
        )
        if existing >= limits[kind]:
            raise ValidationError(f"Ya hay {existing} imagen(es) de ese tipo; el máximo es {limits[kind]}")

        try:
            asset, _created = store_upload(
                company_id=request.company_id,
                upload=request.FILES.get("file"),
                kind=kind,
                owner_type="alignment_record",
                owner_id=record.id,
                caption=(request.data.get("caption") or "").strip(),
                user=request.user,
            )
        except UploadRejectedError as cause:
            raise ValidationError(str(cause)) from cause
        return Response({"id": asset.id, "kind": asset.kind, "caption": asset.caption}, status=201)

    def delete(self, request, record_id: int, photo_id: int):
        record = _writable_record(request, record_id)
        from modules.media.infrastructure.models import MediaAsset

        deleted, _ = (
            MediaAsset.objects.for_company(request.company_id)
            .filter(owner_type="alignment_record", owner_id=record.id, id=photo_id)
            .delete()
        )
        if not deleted:
            raise ValidationError("Esa imagen no es de este alineamiento")
        return Response(status=204)


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


def _frozen(request, group, rpm, standard) -> tuple[list[Band], Tolerance]:
    """The tier's bands and its ✓ line, to freeze with the record."""
    bands = scale_for(request.company_id, group, rpm, standard, getattr(request, "language", "es"))
    return bands, acceptance(bands) or default_tolerance_for(rpm)


def _aligner(raw) -> str:
    if raw not in ALIGNERS:
        raise ValidationError("Alineador desconocido: elige SKF u otro alineador")
    return raw


def _standard(request, standard_id):
    """A norma of this company that judges alignment."""
    if not standard_id:
        return None
    from modules.thresholds.models import ThresholdStandard

    norma = (
        ThresholdStandard.objects.for_company(request.company_id)
        .filter(id=standard_id, is_active=True, techniques__code="alignment")
        .first()
    )
    if norma is None:
        raise ValidationError("Esa norma no existe o no es de alineamiento")
    return norma


class AlignmentScaleView(APIView):
    """The RPM scale of an alignment norma (Q10): what Normas shows and edits.

    Each tier lists its bands — up to these limits, this state — and the
    state above them all. `PUT` replaces the tiers. Records already emitted
    keep the scale they froze, so editing it never repaints a report.
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request, standard_id: int):
        norma = _scale_norma(request, standard_id)
        names = labels(request.company_id, getattr(request, "language", "es"))
        rows = AlignmentTolerance.objects.filter(standard=norma, asset_group__isnull=True).select_related(
            "status"
        )
        return Response(
            {
                "tiers": _tiers_payload(tiers_of(rows, names)),
                "status_options": list(names.values()),
            }
        )

    @tenant_atomic
    def put(self, request, standard_id: int):
        actor = build_actor(request.user, request.company_id)
        if not actor.has("thresholds.manage_standard"):
            raise PermissionDenied("Falta el permiso thresholds.manage_standard")
        norma = _scale_norma(request, standard_id)
        statuses = _statuses(request)
        rows = []
        tiers = []
        for tier in request.data.get("tiers") or []:
            ceiling = int(tier["rpm_ceiling"]) if tier.get("rpm_ceiling") not in (None, "") else None
            bands = []
            for band in tier.get("bands") or []:
                status = _status(statuses, band.get("status_code"))
                bands.append(
                    (status, _required(band.get("parallel_mm")), _required(band.get("angular_mm_per_100mm")))
                )
            beyond = (
                _status(statuses, tier.get("beyond_status_code")) if tier.get("beyond_status_code") else None
            )
            domain = [
                Band(st.code if st else None, "", "", st.severity if st else 0, par, ang)
                for st, par, ang in bands
            ]
            if beyond is not None:
                domain.append(Band(beyond.code, "", "", beyond.severity, None, None))
            try:
                check_bands(domain)
            except InvalidTiersError as cause:
                raise ValidationError(str(cause)) from cause
            line = acceptance(domain)
            tiers.append((ceiling, line.parallel_mm, line.angular_mm_per_100mm))
            rows += [(ceiling, st, par, ang) for st, par, ang in bands]
            if beyond is not None:
                rows.append((ceiling, beyond, None, None))
        try:
            check_tiers(tiers)
        except InvalidTiersError as cause:
            raise ValidationError(str(cause)) from cause

        names = labels(request.company_id)
        current = AlignmentTolerance.objects.filter(standard=norma, asset_group__isnull=True)
        before = _tiers_payload(tiers_of(current.select_related("status"), names))
        current.delete()
        AlignmentTolerance.objects.bulk_create(
            [
                AlignmentTolerance(
                    company_id=request.company_id,
                    standard=norma,
                    rpm_ceiling=ceiling,
                    status=status,
                    parallel_mm=parallel,
                    angular_mm_per_100mm=angular,
                )
                for ceiling, status, parallel, angular in rows
            ]
        )
        after = AlignmentTolerance.objects.filter(standard=norma, asset_group__isnull=True).select_related(
            "status"
        )
        audit.record(
            request,
            "alignment.scale_changed",
            object_type="threshold_standard",
            object_id=norma.id,
            before={"tiers": before},
            after={"tiers": _tiers_payload(tiers_of(after, names))},
        )
        return self.get(request, standard_id)


def _scale_norma(request, standard_id: int):
    from modules.thresholds.models import ThresholdStandard

    norma = ThresholdStandard.objects.for_company(request.company_id).filter(id=standard_id).first()
    if norma is None:
        raise ValidationError("Esa norma no existe")
    return norma


def _statuses(request) -> dict:
    from modules.thresholds.models import Status

    return {row.code: row for row in Status.objects.for_company(request.company_id).filter(kind="condition")}


def _status(statuses: dict, code):
    if not code:
        return None
    if code not in statuses:
        raise ValidationError(f"Estado desconocido: {code}")
    return statuses[code]


def _tiers_payload(tiers) -> list[dict]:
    """Per tier, its bands by limit and the state above them all."""

    def band(item: Band) -> dict:
        return {
            "status_code": item.status_code,
            "status_name": item.status_name,
            "color": item.color,
            "parallel_mm": _plain(item.parallel_mm),
            "angular_mm_per_100mm": _plain(item.angular_mm_per_100mm),
        }

    payload = []
    for ceiling, bands in tiers:
        bounded = sorted((b for b in bands if b.bounded), key=lambda b: b.parallel_mm)
        beyond = next((b for b in bands if not b.bounded), None)
        payload.append(
            {
                "rpm_ceiling": ceiling,
                "bands": [band(item) for item in bounded],
                "beyond": band(beyond) if beyond else None,
            }
        )
    return payload


def _plain(value) -> str | None:
    return None if value is None else format(value.normalize(), "f")


def _required(raw) -> Decimal:
    value = _decimal(raw)
    if value is None:
        raise ValidationError("Cada límite necesita sus dos tolerancias")
    return value


def _phase_fields(phase: str, data) -> dict:
    return {
        f"{phase}_{axis}": _decimal(data.get(f"{phase}_{axis}"))
        for axis in PHASES
        if f"{phase}_{axis}" in data
    }


def _payload(request, record: AlignmentRecord) -> dict:
    tolerance = Tolerance(record.tolerance_parallel_mm, record.tolerance_angular_mm_per_100mm)
    # A record from before states: its ✓ line is its only band.
    bands = bands_from(record.scale_snapshot) or [
        Band(None, "", "", 0, record.tolerance_parallel_mm, record.tolerance_angular_mm_per_100mm)
    ]
    phases = {}
    for phase in ("before", "after"):
        values = AxisValues(*(getattr(record, f"{phase}_{axis}") for axis in PHASES))
        phases[phase] = _phase_payload(values, evaluate(values, tolerance), bands)
    after_verdict = evaluate(AxisValues(*(getattr(record, f"after_{axis}") for axis in PHASES)), tolerance)

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
        "aligner": record.aligner,
        "photo_limits": photo_limits(record.aligner),
        "backlash_within_tolerance": record.backlash_within_tolerance,
        "notes": record.notes,
        "created_at": record.created_at.isoformat(),
        "created_by": record.created_by.get_full_name() if record.created_by else "",
        "standard": (
            {"id": record.standard_id, "name": record.standard.name} if record.standard_id else None
        ),
        "tolerance": {
            "parallel_mm": str(record.tolerance_parallel_mm),
            "angular_mm_per_100mm": str(record.tolerance_angular_mm_per_100mm),
        },
        "scale": [
            {
                "status": _status_payload(band),
                "parallel_mm": _plain(band.parallel_mm),
                "angular_mm_per_100mm": _plain(band.angular_mm_per_100mm),
            }
            for band in bands
        ],
        "before": phases["before"],
        "after": phases["after"],
        # The equipment's state as found and as left (Q10).
        "found_state": phases["before"]["state"],
        "state": phases["after"]["state"],
        "all_ok": after_verdict.all_ok,
        "photos": [
            {
                "id": photo.id,
                "kind": photo.kind,
                "caption": photo.caption,
                "url": backend.url(photo.original_key),
                "thumb_url": backend.url((photo.derivatives or {}).get("thumb", {}).get("key"))
                if (photo.derivatives or {}).get("thumb")
                else None,
            }
            for photo in photos
        ],
    }


def _phase_payload(values: AxisValues, verdict, bands: list[Band]) -> dict:
    states = {axis: state_of(getattr(values, axis), kind_of(axis), bands) for axis in PHASES}
    return {
        **{
            axis: {
                "value": str(getattr(values, axis)) if getattr(values, axis) is not None else None,
                "ok": getattr(verdict, axis),
                "status": _status_payload(states[axis]),
            }
            for axis in PHASES
        },
        "state": _status_payload(worst(list(states.values()))),
    }


def _status_payload(band: Band | None) -> dict | None:
    if band is None or not band.status_code:
        return None
    return {"code": band.status_code, "name": band.status_name, "color": band.color}


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
