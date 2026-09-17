"""The measurement catalogue: service types, units and magnitudes.

A magnitude belongs to exactly one technique, and that is what ties a limit to
the kind of service it judges: pick `vel_rms` and only vibration standards can
apply to it.
"""

from __future__ import annotations

from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.core.domain.i18n import SUPPORTED_LANGUAGES
from modules.measurements.models import Magnitude, Technique, Unit
from modules.security.application.access import build_actor

AGGREGATIONS = ("rms", "peak", "peak_to_peak", "avg", "max")


class TechniqueListView(APIView):
    """The service types: vibration, ultrasound, thermography, oil…"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        language = getattr(request, "language", "es")
        return Response([
            {
                "code": row.code,
                "name": row.translated("name", language),
                "module_code": row.module_code,
                "magnitude_count": row.magnitudes.count(),
                "standard_count": row.standards.count(),
            }
            for row in Technique.objects.prefetch_related("magnitudes", "standards").order_by("code")
        ])


class UnitListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        language = getattr(request, "language", "es")
        return Response([
            {"code": row.code, "name": row.translated("name", language)}
            for row in Unit.objects.order_by("code")
        ])


class MagnitudeListView(APIView):
    """What gets measured. Creating one is configuration, not a release."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        language = getattr(request, "language", "es")
        queryset = Magnitude.objects.select_related("technique", "default_unit").order_by("code")
        if request.query_params.get("technique"):
            queryset = queryset.filter(technique__code=request.query_params["technique"])
        return Response([_payload(row, language) for row in queryset])

    def post(self, request):
        actor = build_actor(request.user, request.company_id)
        if not actor.has("thresholds.manage_set"):
            raise PermissionDenied("Falta el permiso thresholds.manage_set")

        language = getattr(request, "language", "es")
        name = (request.data.get("name") or "").strip()
        if not name:
            raise ValidationError("El nombre es obligatorio")

        technique = Technique.objects.filter(code=request.data.get("technique_code")).first()
        if technique is None:
            raise ValidationError("Debes elegir un tipo de servicio existente")

        unit = Unit.objects.filter(code=request.data.get("unit_code")).first()
        if unit is None:
            raise ValidationError("Debes elegir una unidad existente")

        aggregation = request.data.get("aggregation") or "rms"
        if aggregation not in AGGREGATIONS:
            raise ValidationError(f"Agregación desconocida: {aggregation}")

        code = _slug(request.data.get("code") or name)
        if Magnitude.objects.filter(code=code).exists():
            raise ValidationError(f"Ya existe una medida con el código '{code}'")

        magnitude = Magnitude.objects.create(
            code=code,
            technique=technique,
            name=name,
            default_unit=unit,
            default_aggregation=aggregation,
            decimals=int(request.data.get("decimals") or 2),
            higher_is_worse=bool(request.data.get("higher_is_worse", True)),
            translations={"name": _names(request.data, name)},
        )
        return Response(_payload(magnitude, language), status=201)


def _payload(row: Magnitude, language: str) -> dict:
    return {
        "code": row.code,
        "name": row.translated("name", language),
        "names": row.translations.get("name") or {},
        "technique_code": row.technique.code,
        "technique_name": row.technique.translated("name", language),
        "unit_code": row.default_unit.code,
        "aggregation": row.default_aggregation,
        "decimals": row.decimals,
        # Viscosity and dielectric strength get worse as they drop, unlike
        # every vibration magnitude.
        "higher_is_worse": row.higher_is_worse,
    }


def _slug(value: str) -> str:
    cleaned = "".join(c if c.isalnum() else "_" for c in (value or "").strip().lower())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_")


def _names(payload: dict, fallback: str) -> dict[str, str]:
    names = payload.get("names") or {}
    cleaned = {
        language: str(value).strip()
        for language, value in names.items()
        if language in SUPPORTED_LANGUAGES and str(value).strip()
    }
    return cleaned or {"es": fallback}
