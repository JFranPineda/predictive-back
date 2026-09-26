"""Uploading a thermogram: the unit of work is the image, not a grid cell.

The customer's sheet has no value table for termografía — it is one image per
element observed. Uploading one creates or updates the point's `ir_tmax`
reading (and its `delta_temp`, when a reference was given), linked back to the
image so the record of values can show the thermogram behind the number.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.assets.models import MeasurementPoint
from modules.measurements.domain.thermography import DELTA_TEMP, IR_TMAX, delta_of
from modules.measurements.infrastructure.models import Magnitude, Reading, Unit
from modules.media.domain.flir import extract, suggest_max_celsius
from modules.media.infrastructure.uploads import UploadRejectedError, store_upload
from modules.security.application.access import build_actor
from modules.security.domain.policies import can_record_reading
from modules.services.infrastructure.visit_refs import visit_ref
from modules.services.interfaces.visit_views import _load


class ThermogramView(APIView):
    """`POST service-visits/<id>/thermograms/` — one termogram per call."""

    permission_classes = (IsAuthenticated,)
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, visit_id: int):
        visit = _load(request, visit_id)
        actor = build_actor(request.user, request.company_id)
        if not can_record_reading(actor, visit_ref(visit)):
            raise PermissionDenied("Esta visita no es tuya o ya está cerrada")

        point = (
            MeasurementPoint.objects.for_company(request.company_id)
            .filter(id=request.data.get("point"), equipment=visit.equipment)
            .first()
        )
        if point is None:
            raise ValidationError("Ese punto no pertenece al equipo de la visita")

        upload = request.FILES.get("image")
        if upload is None:
            raise ValidationError("Un termograma necesita una imagen")
        payload = upload.read()
        upload.seek(0)
        try:
            asset, _created = store_upload(
                company_id=request.company_id, upload=upload, kind="thermogram",
                owner_type="point", owner_id=point.id,
                caption=(request.data.get("caption") or "").strip(), user=request.user,
            )
        except UploadRejectedError as cause:
            raise ValidationError(str(cause)) from cause

        tmax = _decimal(request.data.get("tmax"))
        if tmax is None:
            # A JPEG a FLIR camera wrote proposes its own hottest pixel; a
            # plain PNG (what the E4's report page exports) proposes nothing
            # and the technician types it.
            radiometric = extract(payload)
            suggested = suggest_max_celsius(radiometric)
            tmax = Decimal(str(suggested)) if suggested is not None else None

        reference = _decimal(request.data.get("reference"))

        ir_tmax = Magnitude.objects.get(code=IR_TMAX)
        tmax_reading = _write_reading(
            request.company_id, visit, point, ir_tmax, tmax, asset,
        )

        delta_reading = None
        if reference is not None and tmax is not None:
            delta_magnitude = Magnitude.objects.get(code=DELTA_TEMP)
            delta_reading = _write_reading(
                request.company_id, visit, point, delta_magnitude,
                delta_of(tmax, reference), asset,
            )

        return Response({
            "image_id": asset.id,
            "image_url": asset.original_key and _url(asset),
            "tmax_reading_id": tmax_reading.id,
            "tmax": str(tmax_reading.value) if tmax_reading.value is not None else None,
            "delta_reading_id": delta_reading.id if delta_reading else None,
            "delta": str(delta_reading.value) if delta_reading and delta_reading.value is not None else None,
        }, status=201)


def _write_reading(company_id: int, visit, point, magnitude, value, asset) -> Reading:
    """One reading per point/magnitude/visit — re-uploading the same element's
    thermogram in the same visit corrects it, not duplicates it."""
    reading, _ = Reading.objects.update_or_create(
        company_id=company_id, service_visit=visit, point=point, magnitude=magnitude,
        defaults={
            "taken_at": visit.visited_at,
            "unit": magnitude.default_unit or Unit.objects.get(code="°C"),
            "aggregation": magnitude.default_aggregation,
            "value": value,
            "quality": "ok" if value is not None else "not_measured",
            "not_measured_reason": "" if value is not None else "no_access",
            "image": asset,
            # No standard is loaded for a magnitude this new; the record marks
            # it "sin norma" rather than pretending a verdict was reached.
            "condition_status": None,
        },
    )
    return reading


def _url(asset) -> str:
    from modules.media.infrastructure.local_store import store

    return store().url(asset.original_key)


def _decimal(raw) -> Decimal | None:
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw).replace(",", "."))
    except InvalidOperation as cause:
        raise ValidationError(f"'{raw}' no es un número") from cause
