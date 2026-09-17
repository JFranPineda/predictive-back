"""Creating and editing service orders, visits and their participants.

The ownership rule is enforced on every write, not just hidden in the UI: an
external inspector may only touch a visit he is a participant of, and only
while it is open.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.assets.models import Equipment
from modules.diagnostics.models import EquipmentLogEntry
from modules.measurements.models import Instrument, Magnitude, Technique
from modules.security.application.access import build_actor
from modules.security.domain.policies import can_edit_visit, can_write_log_entry
from modules.services.interfaces.visit_views import _load, _reference
from modules.services.models import ServiceOrder, ServiceVisit, VisitParticipant

PARTICIPANT_ROLES = ("lead_analyst", "assistant", "supervisor", "client_witness")


class ServiceAdminView(APIView):
    permission_classes = [IsAuthenticated]

    def actor(self, request):
        return build_actor(request.user, request.company_id)

    def require(self, request, permission: str) -> None:
        if not self.actor(request).has(permission):
            raise PermissionDenied(f"Falta el permiso {permission}")


class ServiceOrderAdminView(ServiceAdminView):
    def post(self, request):
        self.require(request, "services.manage_order")
        from modules.assets.models import Plant

        plant = Plant.objects.for_company(request.company_id).filter(
            id=request.data.get("plant")
        ).first()
        technique = Technique.objects.filter(code=request.data.get("technique")).first()
        if plant is None or technique is None:
            raise ValidationError("Debes elegir una planta y una técnica")

        code = (request.data.get("code") or "").strip()
        if not code:
            raise ValidationError("El código es obligatorio")
        if ServiceOrder.objects.for_company(request.company_id).filter(code=code).exists():
            raise ValidationError(f"Ya existe una orden con el código '{code}'")

        order = ServiceOrder.objects.create(
            company_id=request.company_id, plant=plant, technique=technique, code=code,
            client_work_order=(request.data.get("client_work_order") or "").strip(),
            scheduled_from=request.data.get("scheduled_from") or timezone.now().date(),
            scheduled_to=request.data.get("scheduled_to") or timezone.now().date(),
            status=request.data.get("status") or "planned",
            lead_analyst_id=request.data.get("lead_analyst") or None,
            supervisor_id=request.data.get("supervisor") or None,
        )
        return Response({"id": order.id, "code": order.code}, status=201)


class ServiceOrderDetailView(ServiceAdminView):
    def patch(self, request, order_id: int):
        self.require(request, "services.manage_order")
        order = _find(ServiceOrder.objects.for_company(request.company_id), order_id, "orden")
        for field in ("code", "client_work_order", "status"):
            if field in request.data:
                setattr(order, field, (request.data.get(field) or "").strip())
        for field in ("scheduled_from", "scheduled_to"):
            if request.data.get(field):
                setattr(order, field, request.data[field])
        if "lead_analyst" in request.data:
            order.lead_analyst_id = request.data["lead_analyst"] or None
        order.save()
        return Response({"id": order.id, "code": order.code, "status": order.status})

    def delete(self, request, order_id: int):
        self.require(request, "services.manage_order")
        order = _find(ServiceOrder.objects.for_company(request.company_id), order_id, "orden")
        if order.visits.exists():
            # Cancelling keeps the visits and their readings readable.
            order.status = "cancelled"
            order.save(update_fields=["status"])
            return Response({"id": order.id, "status": "cancelled", "cancelled": True})
        order.delete()
        return Response(status=204)


class VisitCollectionView(ServiceAdminView):
    @transaction.atomic
    def post(self, request):
        self.require(request, "measurements.add_reading")
        order = _find(
            ServiceOrder.objects.for_company(request.company_id),
            request.data.get("service_order"), "orden",
        )
        equipment = _find(
            Equipment.objects.for_company(request.company_id).select_related(
                "asset_group__sector__area"
            ),
            request.data.get("equipment"), "equipo",
        )
        actor = self.actor(request)
        if not actor.may_reach_area(equipment.asset_group.sector.area_id):
            raise PermissionDenied("Ese equipo está fuera de tu alcance")

        instrument = Instrument.objects.for_company(request.company_id).filter(
            id=request.data.get("instrument")
        ).first()
        visit = ServiceVisit.objects.create(
            company_id=request.company_id,
            service_order=order,
            equipment=equipment,
            visited_at=request.data.get("visited_at") or timezone.now(),
            instrument=instrument,
            duration_min=request.data.get("duration_min") or None,
        )
        # Whoever opens a visit is working it; without a participant nobody
        # could edit what they just created.
        VisitParticipant.objects.create(visit=visit, user=request.user, role="lead_analyst")

        if request.data.get("create_readings", True):
            _seed_readings(visit, equipment, request.company_id)
        return Response({"visit_id": visit.id, "equipment": equipment.name}, status=201)


class VisitAdminView(ServiceAdminView):
    def patch(self, request, visit_id: int):
        visit = _load(request, visit_id)
        actor = self.actor(request)
        if not can_edit_visit(actor, _reference(visit)):
            raise PermissionDenied("Esta visita no es tuya o ya está cerrada")

        if request.data.get("visited_at"):
            visit.visited_at = request.data["visited_at"]
        if "instrument" in request.data:
            visit.instrument_id = request.data["instrument"] or None
        if "availability_status" in request.data:
            visit.availability_status_id = request.data["availability_status"] or None
        if "duration_min" in request.data:
            visit.duration_min = request.data["duration_min"] or None
        if request.data.get("close"):
            visit.is_closed = True
            visit.closed_at = timezone.now()
            visit.closed_by = request.user
        elif request.data.get("reopen"):
            if not actor.has("services.close_visit"):
                raise PermissionDenied("Solo un ingeniero puede reabrir una visita")
            visit.is_closed = False
            visit.closed_at = None
        visit.save()
        return Response({"visit_id": visit.id, "is_closed": visit.is_closed})

    def delete(self, request, visit_id: int):
        self.require(request, "services.close_visit")
        visit = _load(request, visit_id)
        if visit.readings.filter(value__isnull=False).exists():
            raise ValidationError(
                "La visita tiene lecturas registradas; ciérrala en vez de eliminarla"
            )
        visit.delete()
        return Response(status=204)


class VisitParticipantView(ServiceAdminView):
    def post(self, request, visit_id: int):
        visit = _load(request, visit_id)
        if not can_edit_visit(self.actor(request), _reference(visit)):
            raise PermissionDenied("Esta visita no es tuya o ya está cerrada")
        role = request.data.get("role") or "assistant"
        if role not in PARTICIPANT_ROLES:
            raise ValidationError(f"Rol desconocido: {role}")
        participant, created = VisitParticipant.objects.get_or_create(
            visit=visit, user_id=request.data.get("user"), defaults={"role": role}
        )
        if not created:
            participant.role = role
            participant.save(update_fields=["role"])
        return Response({"user_id": participant.user_id, "role": participant.role}, status=201)

    def delete(self, request, visit_id: int):
        visit = _load(request, visit_id)
        if not can_edit_visit(self.actor(request), _reference(visit)):
            raise PermissionDenied("Esta visita no es tuya o ya está cerrada")
        if visit.participants.count() <= 1:
            # A visit with nobody on it can never be edited again.
            raise ValidationError("Una visita necesita al menos un ejecutante")
        visit.participants.filter(user_id=request.query_params.get("user")).delete()
        return Response(status=204)


class LogEntryDetailView(ServiceAdminView):
    def patch(self, request, entry_id: int):
        entry = _find(
            EquipmentLogEntry.objects.for_company(request.company_id).select_related(
                "service_visit"
            ),
            entry_id, "anotación",
        )
        self._assert_writable(request, entry)
        if "text" in request.data:
            entry.text = (request.data.get("text") or "").strip()
        if "entry_type" in request.data:
            entry.entry_type = request.data["entry_type"]
        if "status" in request.data:
            if not self.actor(request).has("diagnostics.close_recommendation"):
                raise PermissionDenied("Solo un ingeniero cierra recomendaciones")
            entry.status = request.data["status"]
        entry.save()
        return Response({"id": entry.id, "text": entry.text, "status": entry.status or None})

    def delete(self, request, entry_id: int):
        entry = _find(
            EquipmentLogEntry.objects.for_company(request.company_id).select_related(
                "service_visit"
            ),
            entry_id, "anotación",
        )
        self._assert_writable(request, entry)
        entry.delete()
        return Response(status=204)

    def _assert_writable(self, request, entry: EquipmentLogEntry) -> None:
        actor = self.actor(request)
        if entry.service_visit_id is None:
            if not actor.has("diagnostics.close_recommendation"):
                raise PermissionDenied("Esa anotación no pertenece a una visita")
            return
        visit = _load(request, entry.service_visit_id)
        if not can_write_log_entry(actor, _reference(visit)):
            raise PermissionDenied("Esta visita no es tuya o ya está cerrada")
        if entry.author_id not in (None, request.user.id) and not actor.has(
            "diagnostics.close_recommendation"
        ):
            # Each line keeps its author; rewriting somebody else's conclusion
            # is how a report stops being trustworthy.
            raise PermissionDenied("Esa anotación la escribió otra persona")


def _seed_readings(visit: ServiceVisit, equipment: Equipment, company_id: int) -> None:
    """Empty rows for every point and magnitude the technique measures, so the
    field form opens ready to be typed into."""
    from modules.measurements.models import Reading

    technique = visit.service_order.technique
    magnitudes = list(Magnitude.objects.filter(technique=technique).select_related("default_unit"))
    points = list(equipment.points.filter(is_active=True))
    Reading.objects.bulk_create([
        Reading(
            company_id=company_id, taken_at=visit.visited_at, point=point, service_visit=visit,
            magnitude=magnitude, value=None, unit=magnitude.default_unit,
            aggregation=magnitude.default_aggregation, quality="not_measured",
        )
        for point in points
        for magnitude in magnitudes
    ])


def _find(queryset, pk, label: str):
    row = queryset.filter(id=pk).first() if pk else None
    if row is None:
        raise ValidationError(f"Esa {label} no existe")
    return row
