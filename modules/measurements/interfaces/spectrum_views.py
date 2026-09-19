"""Spectra of a point: the capture, the numbers, or both.

The list never carries the curve. A spectrum is 800 to 3200 pairs and a point
accumulates one per round; sending them all so a page can draw six thumbnails
is what makes a gallery feel broken. The curve is its own endpoint, fetched
when somebody actually opens one.
"""

from __future__ import annotations

import gzip
import json

from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.assets.models import MeasurementPoint
from modules.measurements.domain.spectra import SpectrumFormatError, parse_csv
from modules.measurements.models import Spectrum
from modules.media.infrastructure.local_store import store
from modules.security.application.access import build_actor

MAX_CSV_BYTES = 8 * 1024 * 1024
PAGE_SIZE = 50


class SpectrumCollectionView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        queryset = (
            Spectrum.objects.for_company(request.company_id)
            .select_related("point__equipment", "image", "unit")
            .prefetch_related("diagnosis")
        )
        if request.query_params.get("point"):
            queryset = queryset.filter(point_id=int(request.query_params["point"]))
        elif request.query_params.get("equipment"):
            queryset = queryset.filter(
                point__equipment_id=int(request.query_params["equipment"])
            )
        if request.query_params.get("type"):
            queryset = queryset.filter(spectrum_type=request.query_params["type"])
        if request.query_params.get("visit"):
            queryset = queryset.filter(service_visit_id=int(request.query_params["visit"]))

        limit = min(int(request.query_params.get("limit") or PAGE_SIZE), 200)
        backend = store()
        return Response([_payload(row, backend) for row in queryset[:limit]])

    def post(self, request):
        _require(request, "vibration.add_reading", "measurements.add_reading")

        point = (
            MeasurementPoint.objects.for_company(request.company_id)
            .filter(id=request.data.get("point"))
            .first()
        )
        if point is None:
            raise ValidationError("Debes elegir un punto de medición")

        spectrum = Spectrum(
            company_id=request.company_id,
            point=point,
            reading_id=request.data.get("reading") or None,
            service_visit_id=request.data.get("visit") or None,
            taken_at=request.data.get("taken_at") or _now(),
            spectrum_type=request.data.get("spectrum_type") or "velocity",
            rpm_at_capture=_float(request.data.get("rpm_at_capture")),
            window=(request.data.get("window") or "")[:20],
            averages=_int(request.data.get("averages")),
            image_id=request.data.get("image") or None,
            caption=(request.data.get("caption") or "").strip()[:300],
        )

        upload = request.FILES.get("data")
        if upload is not None:
            spectrum = _attach_curve(spectrum, upload, request.company_id)
        elif spectrum.image_id is None:
            raise ValidationError(
                "Un espectro necesita al menos una captura o un archivo de datos"
            )

        spectrum.save()
        if request.data.get("diagnosis"):
            spectrum.diagnosis.set(
                [int(value) for value in request.data.getlist("diagnosis")]
            )
        return Response(_payload(spectrum, store()), status=201)


class SpectrumDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, spectrum_id: int):
        spectrum = _get(request, spectrum_id)
        return Response(_payload(spectrum, store()))

    def patch(self, request, spectrum_id: int):
        """The caption and the diagnosis are written after looking at it.

        In the source reports the text under a spectrum *is* the finding, and
        it is refined on review — so it cannot be write-once.
        """
        _require(request, "vibration.diagnose", "measurements.add_reading")
        spectrum = _get(request, spectrum_id)

        if "caption" in request.data:
            spectrum.caption = (request.data.get("caption") or "").strip()[:300]
        for field in ("spectrum_type", "window"):
            if field in request.data:
                setattr(spectrum, field, request.data.get(field) or getattr(spectrum, field))
        if "rpm_at_capture" in request.data:
            spectrum.rpm_at_capture = _float(request.data["rpm_at_capture"])
        spectrum.save()
        if "diagnosis" in request.data:
            values = request.data.getlist("diagnosis") if hasattr(
                request.data, "getlist"
            ) else request.data["diagnosis"]
            spectrum.diagnosis.set([int(value) for value in (values or [])])
        return Response(_payload(_get(request, spectrum_id), store()))

    def delete(self, request, spectrum_id: int):
        _require(request, "vibration.diagnose", "measurements.add_reading")
        spectrum = _get(request, spectrum_id)
        if spectrum.data_key:
            try:
                store().delete(spectrum.data_key)
            except (OSError, ValueError):
                pass
        spectrum.delete()
        return Response(status=204)


class SpectrumCurveView(APIView):
    """The numbers themselves, only when somebody opens the spectrum."""

    permission_classes = [IsAuthenticated]

    def get(self, request, spectrum_id: int):
        spectrum = _get(request, spectrum_id)
        if not spectrum.data_key:
            raise ValidationError("Este espectro sólo tiene captura, no datos numéricos")
        try:
            raw = store().get(spectrum.data_key)
        except (OSError, ValueError):
            raise ValidationError("El archivo de datos ya no está disponible") from None
        return Response(json.loads(gzip.decompress(raw).decode()))


def _attach_curve(spectrum: Spectrum, upload, company_id: int) -> Spectrum:
    if upload.size > MAX_CSV_BYTES:
        raise ValidationError("El archivo de datos supera los 8 MB")
    try:
        curve = parse_csv(upload.read().decode("utf-8-sig", errors="ignore"))
    except SpectrumFormatError as cause:
        raise ValidationError(str(cause)) from cause

    peak = curve.peak
    span = curve.span
    spectrum.lines = len(curve)
    spectrum.fmin_hz, spectrum.fmax_hz = span if span else (None, None)
    spectrum.peak_hz, spectrum.peak_amplitude = peak if peak else (None, None)

    # Content-addressed like the images, so re-importing the same export twice
    # costs one object.
    from modules.media.infrastructure.local_store import checksum

    body = gzip.compress(json.dumps(curve.as_dict()).encode())
    key = f"spectra/{company_id}/{checksum(body)[:2]}/{checksum(body)}.json.gz"
    store().put(key, body, content_type="application/gzip")
    spectrum.data_key = key
    return spectrum


def _payload(spectrum: Spectrum, backend) -> dict:
    image = spectrum.image
    thumb = (image.derivatives or {}).get("thumb", {}).get("key") if image else None
    return {
        "id": spectrum.id,
        "point_id": spectrum.point_id,
        "point_label": spectrum.point.label,
        "equipment_id": spectrum.point.equipment_id,
        "taken_at": spectrum.taken_at.isoformat(),
        "spectrum_type": spectrum.spectrum_type,
        "visit_id": spectrum.service_visit_id,
        "fmin_hz": spectrum.fmin_hz,
        "fmax_hz": spectrum.fmax_hz,
        "lines": spectrum.lines,
        "rpm_at_capture": spectrum.rpm_at_capture,
        "window": spectrum.window,
        "averages": spectrum.averages,
        "unit": spectrum.unit.code if spectrum.unit else "",
        "peak_hz": spectrum.peak_hz,
        "peak_amplitude": spectrum.peak_amplitude,
        "has_numeric_data": spectrum.has_numeric_data,
        "image_url": backend.url(image.original_key) if image else None,
        "thumb_url": backend.url(thumb) if thumb else None,
        "caption": spectrum.caption,
        "diagnosis": [
            {"id": fault.id, "code": fault.code, "name": fault.name}
            for fault in spectrum.diagnosis.all()
        ],
    }


def _get(request, spectrum_id: int) -> Spectrum:
    spectrum = (
        Spectrum.objects.for_company(request.company_id)
        .select_related("point__equipment", "image", "unit")
        .prefetch_related("diagnosis")
        .filter(id=spectrum_id)
        .first()
    )
    if spectrum is None:
        raise ValidationError("Ese espectro no existe")
    return spectrum


def _require(request, *permissions: str) -> None:
    actor = build_actor(request.user, request.company_id)
    if not any(actor.has(permission) for permission in permissions):
        raise PermissionDenied(f"Falta el permiso {permissions[0]}")


def _now():
    from django.utils import timezone

    return timezone.now()


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
