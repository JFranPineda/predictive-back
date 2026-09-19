"""Operating conditions captured with each service."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.operating_data.models import OperatingParameter, OperatingReading
from modules.security.application.access import build_actor
from modules.security.domain.policies import can_edit_visit
from modules.services.interfaces.visit_views import _load, _reference


class ParameterListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        language = getattr(request, "language", "es")
        queryset = OperatingParameter.objects.for_company(request.company_id).filter(
            is_active=True
        )
        technique = request.query_params.get("technique")
        if technique:
            # A parameter with no technique is general: rpm and running hours
            # are worth recording whatever is being measured.
            queryset = queryset.filter(technique_code__in=["", technique])
        return Response([
            {
                "id": row.id,
                "code": row.code,
                "name": row.translated("name", language),
                "technique_code": row.technique_code,
                "unit_code": row.unit_code,
                "decimals": row.decimals,
                "is_cumulative": row.is_cumulative,
                "applies_to": row.applies_to,
            }
            for row in queryset
        ])

    def post(self, request):
        actor = build_actor(request.user, request.company_id)
        if not actor.has("operating_data.add"):
            raise PermissionDenied("Falta el permiso operating_data.add")
        name = (request.data.get("name") or "").strip()
        if not name:
            raise ValidationError("El nombre es obligatorio")
        code = _slug(request.data.get("code") or name)
        if OperatingParameter.objects.for_company(request.company_id).filter(code=code).exists():
            raise ValidationError(f"Ya existe el parámetro '{code}'")
        parameter = OperatingParameter.objects.create(
            company_id=request.company_id, code=code, name=name,
            unit_code=(request.data.get("unit_code") or "").strip(),
            technique_code=(request.data.get("technique_code") or "").strip(),
            decimals=int(request.data.get("decimals") or 1),
            is_cumulative=bool(request.data.get("is_cumulative")),
            translations={"name": {"es": name}},
        )
        return Response({"code": parameter.code, "name": parameter.name}, status=201)


class ParameterDetailView(APIView):
    """Correcting a parameter, and retiring one that is no longer taken.

    `is_cumulative` is the one that matters: a running-hour counter that only
    grows is read differently from a pressure, and a parameter created with
    the flag wrong reports nonsense trends until somebody can fix it.
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request, parameter_id: int):
        parameter = _parameter(request, parameter_id)
        _may_manage(request)
        name = (request.data.get("name") or "").strip()
        if name:
            parameter.name = name
            parameter.translations = {
                **parameter.translations,
                "name": {**(parameter.translations.get("name") or {}), "es": name},
            }
        for field in ("unit_code", "technique_code"):
            if field in request.data:
                setattr(parameter, field, (request.data.get(field) or "").strip())
        if "decimals" in request.data:
            parameter.decimals = max(int(request.data["decimals"] or 0), 0)
        if "is_cumulative" in request.data:
            parameter.is_cumulative = bool(request.data["is_cumulative"])
        if "is_active" in request.data:
            parameter.is_active = bool(request.data["is_active"])
        parameter.save()
        language = getattr(request, "language", "es")
        return Response({
            "id": parameter.id, "code": parameter.code,
            "name": parameter.translated("name", language),
            "unit_code": parameter.unit_code, "technique_code": parameter.technique_code,
            "decimals": parameter.decimals, "is_cumulative": parameter.is_cumulative,
            "is_active": parameter.is_active,
        })

    def delete(self, request, parameter_id: int):
        parameter = _parameter(request, parameter_id)
        _may_manage(request)
        from modules.operating_data.models import OperatingReading

        used = OperatingReading.objects.filter(parameter=parameter).count()
        if used:
            # The values already recorded are what a trend is drawn from.
            parameter.is_active = False
            parameter.save(update_fields=["is_active"])
            return Response({"id": parameter.id, "is_active": False, "deactivated": True,
                             "reason": f"tiene {used} valor(es) registrados"})
        parameter.delete()
        return Response(status=204)


def _parameter(request, parameter_id: int):
    row = OperatingParameter.objects.for_company(request.company_id).filter(
        id=parameter_id
    ).first()
    if row is None:
        raise ValidationError("Ese parámetro no existe")
    return row


def _may_manage(request) -> None:
    actor = build_actor(request.user, request.company_id)
    if not actor.has("operating_data.add"):
        raise PermissionDenied("Falta el permiso operating_data.add")


class VisitOperatingView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, visit_id: int):
        language = getattr(request, "language", "es")
        visit = _load(request, visit_id)
        stored = {
            row.parameter.code: row
            for row in visit.operating_readings.select_related("parameter")
        }
        technique = visit.service_order.technique.code
        parameters = OperatingParameter.objects.for_company(request.company_id).filter(
            is_active=True, technique_code__in=["", technique]
        )
        return Response([
            {
                "code": parameter.code,
                "name": parameter.translated("name", language),
                "unit_code": parameter.unit_code,
                "decimals": parameter.decimals,
                "value": str(stored[parameter.code].value)
                if parameter.code in stored and stored[parameter.code].value is not None
                else None,
                "text_value": stored[parameter.code].text_value if parameter.code in stored else "",
            }
            for parameter in parameters
            if not parameter.applies_to
            or visit.equipment.equipment_type in parameter.applies_to
        ])

    @transaction.atomic
    def put(self, request, visit_id: int):
        visit = _load(request, visit_id)
        actor = build_actor(request.user, request.company_id)
        if not can_edit_visit(actor, _reference(visit)):
            raise PermissionDenied("Esta visita no es tuya o ya está cerrada")

        parameters = {
            row.code: row
            for row in OperatingParameter.objects.for_company(request.company_id)
        }
        saved = 0
        for entry in request.data.get("values", []):
            parameter = parameters.get(entry.get("code"))
            if parameter is None:
                continue
            OperatingReading.objects.update_or_create(
                service_visit=visit,
                parameter=parameter,
                defaults={
                    "company_id": request.company_id,
                    "equipment": visit.equipment,
                    "value": _decimal(entry.get("value")),
                    "text_value": (entry.get("text_value") or "").strip()[:120],
                    "taken_at": visit.visited_at,
                },
            )
            saved += 1
        return Response({"saved": saved})


def _decimal(raw):
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw).replace(",", "."))
    except InvalidOperation as exc:
        raise ValidationError(f"'{raw}' no es un número") from exc


def _slug(value: str) -> str:
    cleaned = "".join(c if c.isalnum() else "_" for c in (value or "").strip().lower())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "param"
