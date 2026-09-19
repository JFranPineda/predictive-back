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
        from django.db.models import Count

        # `Magnitude.default_unit` is `related_name="+"`, so there is no
        # reverse accessor to annotate through: one grouped query answers it.
        used = dict(
            Magnitude.objects.values_list("default_unit_id")
            .annotate(total=Count("id"))
            .values_list("default_unit_id", "total")
        )
        return Response([
            {
                "id": row.id,
                "code": row.code,
                "name": row.translated("name", language),
                "names": row.translations.get("name") or {},
                # A unit magnitudes are reported in cannot be deleted without
                # lying about every reading already taken in it.
                "magnitude_count": used.get(row.id, 0),
            }
            for row in Unit.objects.order_by("code")
        ])

    def post(self, request):
        actor = build_actor(request.user, request.company_id)
        if not actor.has("thresholds.manage_set"):
            raise PermissionDenied("Falta el permiso thresholds.manage_set")

        code = (request.data.get("code") or "").strip()
        name = (request.data.get("name") or "").strip()
        if not code or not name:
            raise ValidationError("El símbolo y el nombre son obligatorios")
        if Unit.objects.filter(code=code).exists():
            raise ValidationError(f"Ya existe la unidad '{code}'")
        unit = Unit.objects.create(
            code=code, name=name, translations={"name": _names(request.data, name)}
        )
        return Response({"code": unit.code, "name": unit.name}, status=201)


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


class UnitDetailView(APIView):
    """Renaming a unit is configuration; deleting one that is in use is not.

    The symbol is what the customer reads next to every value, so it stays
    editable — but a unit a magnitude is reported in is refused, because the
    readings already taken carry it.
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request, unit_id: int):
        unit = _unit(unit_id)
        _may_manage(request)

        code = (request.data.get("code") or "").strip()
        if code and code != unit.code:
            if Unit.objects.filter(code=code).exclude(id=unit.id).exists():
                raise ValidationError(f"Ya existe la unidad '{code}'")
            unit.code = code
        name = (request.data.get("name") or "").strip()
        if name:
            unit.name = name
            unit.translations = {
                **unit.translations,
                "name": {**(unit.translations.get("name") or {}), **_names(request.data, name)},
            }
        # `Unit` is a plain catalogue row: no timestamps to touch.
        unit.save(update_fields=["code", "name", "translations"])
        language = getattr(request, "language", "es")
        return Response({
            "id": unit.id, "code": unit.code, "name": unit.translated("name", language),
        })

    def delete(self, request, unit_id: int):
        unit = _unit(unit_id)
        _may_manage(request)
        used = Magnitude.objects.filter(default_unit=unit).count()
        if used:
            raise ValidationError(
                f"No se puede borrar: {used} magnitud(es) se reportan en esta unidad"
            )
        unit.delete()
        return Response(status=204)


def _unit(unit_id: int) -> Unit:
    unit = Unit.objects.filter(id=unit_id).first()
    if unit is None:
        raise ValidationError("Esa unidad no existe")
    return unit


def _may_manage(request) -> None:
    actor = build_actor(request.user, request.company_id)
    if not actor.has("thresholds.manage_set"):
        raise PermissionDenied("Falta el permiso thresholds.manage_set")


class MagnitudeDetailView(APIView):
    """What is measured, corrected in place.

    The decimals and the direction are not cosmetics: `higher_is_worse=False`
    is what makes a viscosity report read the right way round, and a magnitude
    created with it wrong cannot be fixed by deleting it once readings exist.
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request, magnitude_id: int):
        magnitude = _magnitude(magnitude_id)
        _may_manage(request)

        name = (request.data.get("name") or "").strip()
        if name:
            magnitude.name = name
            magnitude.translations = {
                **magnitude.translations,
                "name": {
                    **(magnitude.translations.get("name") or {}),
                    **_names(request.data, name),
                },
            }
        if request.data.get("default_unit"):
            unit = Unit.objects.filter(code=request.data["default_unit"]).first()
            if unit is None:
                raise ValidationError("Esa unidad no existe")
            magnitude.default_unit = unit
        if request.data.get("default_aggregation"):
            magnitude.default_aggregation = request.data["default_aggregation"]
        if "higher_is_worse" in request.data:
            magnitude.higher_is_worse = bool(request.data["higher_is_worse"])
        if "decimals" in request.data:
            magnitude.decimals = max(int(request.data["decimals"] or 0), 0)
        magnitude.save()
        language = getattr(request, "language", "es")
        return Response({
            "id": magnitude.id, "code": magnitude.code,
            "name": magnitude.translated("name", language),
            "technique_code": magnitude.technique.code,
            "unit_code": magnitude.default_unit.code,
            "default_aggregation": magnitude.default_aggregation,
            "higher_is_worse": magnitude.higher_is_worse,
            "decimals": magnitude.decimals,
        })

    def delete(self, request, magnitude_id: int):
        magnitude = _magnitude(magnitude_id)
        _may_manage(request)
        from modules.measurements.models import Reading

        readings = Reading.objects.filter(magnitude=magnitude).count()
        if readings:
            raise ValidationError(
                f"No se puede borrar: {readings} lectura(s) se tomaron en esta magnitud"
            )
        from modules.thresholds.models import ThresholdSet

        sets = ThresholdSet.objects.filter(magnitude_code=magnitude.code).count()
        if sets:
            raise ValidationError(f"No se puede borrar: {sets} juego(s) de umbrales la juzgan")
        magnitude.delete()
        return Response(status=204)


def _magnitude(magnitude_id: int) -> Magnitude:
    magnitude = Magnitude.objects.select_related("technique", "default_unit").filter(
        id=magnitude_id
    ).first()
    if magnitude is None:
        raise ValidationError("Esa magnitud no existe")
    return magnitude


class InstrumentListView(APIView):
    """The instruments a round is taken with.

    They were seeded and never manageable, which meant a calibration date
    nobody could update — and a reading taken with an expired instrument is
    not a reading anybody can defend.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from datetime import date

        from modules.measurements.models import Instrument

        today = date.today()
        return Response([
            {
                "id": row.id, "code": row.code, "name": row.name,
                "manufacturer": row.manufacturer, "serial_number": row.serial_number,
                "last_calibration": row.last_calibration,
                "next_calibration": row.next_calibration,
                "is_expired": bool(row.next_calibration and row.next_calibration < today),
            }
            for row in Instrument.objects.for_company(request.company_id).order_by("name")
        ])

    def post(self, request):
        from modules.measurements.models import Instrument

        _may_manage(request)
        name = (request.data.get("name") or "").strip()
        if not name:
            raise ValidationError("El nombre es obligatorio")
        code = _slug(request.data.get("code") or name)
        if Instrument.objects.for_company(request.company_id).filter(code=code).exists():
            raise ValidationError(f"Ya existe el instrumento '{code}'")
        instrument = Instrument.objects.create(
            company_id=request.company_id, code=code, name=name,
            manufacturer=(request.data.get("manufacturer") or "").strip(),
            serial_number=(request.data.get("serial_number") or "").strip(),
            last_calibration=request.data.get("last_calibration") or None,
            next_calibration=request.data.get("next_calibration") or None,
        )
        return Response({"id": instrument.id, "code": instrument.code}, status=201)


class InstrumentDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, instrument_id: int):
        instrument = _instrument(request, instrument_id)
        _may_manage(request)
        for field in ("name", "manufacturer", "serial_number"):
            if field in request.data:
                setattr(instrument, field, (request.data.get(field) or "").strip())
        for field in ("last_calibration", "next_calibration"):
            if field in request.data:
                setattr(instrument, field, request.data.get(field) or None)
        instrument.save()
        return Response({"id": instrument.id, "code": instrument.code, "name": instrument.name})

    def delete(self, request, instrument_id: int):
        instrument = _instrument(request, instrument_id)
        _may_manage(request)
        from modules.measurements.models import Reading
        from modules.services.models import ServiceVisit

        used = (
            Reading.objects.filter(instrument=instrument).count()
            + ServiceVisit.objects.filter(instrument=instrument).count()
        )
        if used:
            raise ValidationError(
                f"No se puede borrar: {used} lectura(s) y visita(s) se tomaron con él"
            )
        instrument.delete()
        return Response(status=204)


def _instrument(request, instrument_id: int):
    from modules.measurements.models import Instrument

    row = Instrument.objects.for_company(request.company_id).filter(id=instrument_id).first()
    if row is None:
        raise ValidationError("Ese instrumento no existe")
    return row
