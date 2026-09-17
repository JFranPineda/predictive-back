"""The machine's nameplate, and the ISO class that follows from it."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.assets.models import Equipment
from modules.nameplate.models import NameplateData
from modules.security.application.access import build_actor

HP_PER_KW = 1 / 0.7457

FIELDS = (
    "manufacturer", "model", "serial_number", "frame_size", "mounting",
    "bearing_de", "bearing_nde", "lubricant", "source", "notes",
)
NUMBERS = ("rated_power_kw", "rated_current_a")
INTEGERS = ("year", "rated_rpm", "rated_voltage_v", "lubricant_interval_h")


class NameplateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, equipment_id: int):
        equipment = _equipment(request, equipment_id)
        plate = getattr(equipment, "nameplate", None)
        return Response(_payload(equipment, plate))

    def put(self, request, equipment_id: int):
        actor = build_actor(request.user, request.company_id)
        if not actor.has("nameplate.manage"):
            raise PermissionDenied("Falta el permiso nameplate.manage")

        equipment = _equipment(request, equipment_id)
        plate, _ = NameplateData.objects.get_or_create(
            equipment=equipment, defaults={"company_id": request.company_id}
        )
        for field in FIELDS:
            if field in request.data:
                setattr(plate, field, (request.data.get(field) or "").strip())
        for field in NUMBERS:
            if field in request.data:
                setattr(plate, field, _decimal(request.data[field]))
        for field in INTEGERS:
            if field in request.data:
                setattr(plate, field, _integer(request.data[field]))

        # The crew reads horsepower off the plate; the ISO tables are in kW.
        if request.data.get("rated_power_hp") not in (None, ""):
            horsepower = _decimal(request.data["rated_power_hp"])
            if horsepower is not None:
                plate.rated_power_kw = round(horsepower * Decimal("0.7457"), 2)

        plate.save()
        return Response(_payload(equipment, plate))


def _payload(equipment: Equipment, plate: NameplateData | None) -> dict:
    data = {
        "equipment_id": equipment.id,
        "equipment_name": equipment.name,
        "has_nameplate": plate is not None,
        "rated_power_kw": str(plate.rated_power_kw) if plate and plate.rated_power_kw else None,
        "rated_power_hp": plate.rated_power_hp if plate else None,
        "mounting": plate.mounting if plate else "",
        "resolved_class": _resolved_class(equipment, plate),
    }
    for field in FIELDS + INTEGERS:
        data[field] = getattr(plate, field, "") if plate else ""
    data["rated_current_a"] = (
        str(plate.rated_current_a) if plate and plate.rated_current_a else None
    )
    return data


def _resolved_class(equipment: Equipment, plate: NameplateData | None) -> dict | None:
    """What the standard would grade this machine as, so the screen can show
    the consequence of the number the user just typed."""
    from modules.thresholds.infrastructure.repositories import standard_to_domain

    if equipment.applied_standard_id is None or plate is None:
        return None
    standard = standard_to_domain(equipment.applied_standard)
    machine_class = standard.classify(
        float(plate.rated_power_kw) if plate.rated_power_kw else None,
        plate.mounting or None,
    )
    if machine_class is None:
        return None
    return {
        "code": machine_class.code,
        "name": machine_class.name,
        "standard": standard.name,
        "explicit": equipment.machine_class_id is not None,
    }


def _equipment(request, equipment_id: int) -> Equipment:
    equipment = (
        Equipment.objects.for_company(request.company_id)
        .select_related("applied_standard", "machine_class")
        .filter(id=equipment_id)
        .first()
    )
    if equipment is None:
        raise ValidationError("Ese equipo no existe")
    return equipment


def _decimal(raw) -> Decimal | None:
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw).replace(",", "."))
    except InvalidOperation as exc:
        raise ValidationError(f"'{raw}' no es un número") from exc


def _integer(raw) -> int | None:
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"'{raw}' no es un entero") from exc
