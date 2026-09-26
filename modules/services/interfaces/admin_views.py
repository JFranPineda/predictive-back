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
from modules.core.infrastructure.audit import record
from modules.core.infrastructure.transactions import tenant_atomic
from modules.diagnostics.models import EquipmentLogEntry
from modules.licensing.infrastructure.context import current_alias
from modules.measurements.domain.families import is_offered
from modules.measurements.models import Instrument, Technique
from modules.security.application.access import build_actor
from modules.security.domain.policies import (
    can_change_order_status,
    can_edit_visit,
    can_write_log_entry,
)
from modules.services.domain.order_status import CANCELLED, PLANNED, can_transition
from modules.services.infrastructure.order_queries import analysts_of
from modules.services.infrastructure.visit_refs import visit_ref
from modules.services.interfaces.visit_views import _load
from modules.services.models import ServiceOrder, ServiceProvider, ServiceVisit, VisitParticipant

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
        if not is_offered(technique.family):
            raise ValidationError(f"{technique.name} no es un servicio que se ordene")

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
            # A new order starts planned; moving it on is the administrator's.
            status=PLANNED,
            provider=_provider(request, request.data.get("provider")),
            lead_analyst_id=_analyst(request, request.data.get("lead_analyst")),
            supervisor_id=request.data.get("supervisor") or None,
        )
        return Response({"id": order.id, "code": order.code}, status=201)


class ServiceOrderDetailView(ServiceAdminView):
    """Plant and technique are what every visit of the round hangs off, so they
    are never changed here; the form shows them locked."""

    @tenant_atomic
    def patch(self, request, order_id: int):
        self.require(request, "services.manage_order")
        order = _find(ServiceOrder.objects.for_company(request.company_id), order_id, "orden")
        for field in ("code", "client_work_order"):
            if field in request.data:
                setattr(order, field, (request.data.get(field) or "").strip())
        if not order.code:
            raise ValidationError("El código es obligatorio")
        for field in ("scheduled_from", "scheduled_to"):
            if request.data.get(field):
                setattr(order, field, request.data[field])
        if "provider" in request.data:
            order.provider = _provider(request, request.data["provider"])
        if "lead_analyst" in request.data:
            order.lead_analyst_id = _analyst(request, request.data["lead_analyst"])
        if "status" in request.data and request.data["status"] != order.status:
            self._change_status(request, order, request.data["status"])
        order.save()
        return Response({"id": order.id, "code": order.code, "status": order.status})

    def delete(self, request, order_id: int):
        self.require(request, "services.manage_order")
        order = _find(ServiceOrder.objects.for_company(request.company_id), order_id, "orden")
        if order.visits.exists():
            # Cancelling keeps the visits and their readings readable; it is a
            # change of status like any other.
            with transaction.atomic(using=current_alias()):
                self._change_status(request, order, CANCELLED)
                order.save(update_fields=["status"])
            return Response({"id": order.id, "status": CANCELLED, "cancelled": True})
        order.delete()
        return Response(status=204)

    def _change_status(self, request, order: ServiceOrder, target: str) -> None:
        if not can_change_order_status(self.actor(request)):
            raise PermissionDenied("Solo el administrador cambia el estado de una orden")
        if not can_transition(order.status, target):
            raise ValidationError(f"Una orden {order.get_status_display().lower()} no pasa a ese estado")
        record(request, "service_order.status", object_type="service_order", object_id=order.id,
               before={"status": order.status}, after={"status": target})
        order.status = target


def _provider(request, provider_id) -> ServiceProvider | None:
    if not provider_id:
        return None
    provider = ServiceProvider.objects.for_company(request.company_id).filter(id=provider_id).first()
    if provider is None:
        raise ValidationError("Esa empresa no existe")
    return provider


def _analyst(request, user_id) -> int | None:
    if not user_id:
        return None
    if int(user_id) not in {row["id"] for row in analysts_of(request.company_id)}:
        raise ValidationError("El analista debe ser un ingeniero de la compañía")
    return int(user_id)


class VisitCollectionView(ServiceAdminView):
    @tenant_atomic
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

        warning = None
        if order.technique.code == "oil_analysis" and equipment.lubrication_type == "grease":
            warning = "Este equipo está registrado con grasa, no aceite"
        return Response(
            {"visit_id": visit.id, "equipment": equipment.name, "warning": warning}, status=201
        )


class VisitAdminView(ServiceAdminView):
    def patch(self, request, visit_id: int):
        visit = _load(request, visit_id)
        actor = self.actor(request)
        if not can_edit_visit(actor, visit_ref(visit)):
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
            reason = _close_blocker(visit)
            if reason:
                raise ValidationError(reason)
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
        if not can_edit_visit(self.actor(request), visit_ref(visit)):
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
        if not can_edit_visit(self.actor(request), visit_ref(visit)):
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
        if not can_write_log_entry(actor, visit_ref(visit)):
            raise PermissionDenied("Esta visita no es tuya o ya está cerrada")
        if entry.author_id not in (None, request.user.id) and not actor.has(
            "diagnostics.close_recommendation"
        ):
            # Each line keeps its author; rewriting somebody else's conclusion
            # is how a report stops being trustworthy.
            raise PermissionDenied("Esa anotación la escribió otra persona")


def _seed_readings(visit: ServiceVisit, equipment: Equipment, company_id: int) -> None:
    """Empty rows for every point and magnitude the round reads, so the field
    form opens ready to be typed into. Opt-in magnitudes (acceleration) only
    where the kind's template asks for them."""
    from modules.measurements.infrastructure.point_plan import magnitude_plan
    from modules.measurements.models import Reading

    Reading.objects.bulk_create([
        Reading(
            company_id=company_id, taken_at=visit.visited_at, point=point, service_visit=visit,
            magnitude=magnitude, value=None, unit=magnitude.default_unit,
            aggregation=magnitude.default_aggregation, quality="not_measured",
        )
        for point, magnitude in magnitude_plan(equipment, visit.service_order.technique)
    ])


def _find(queryset, pk, label: str):
    row = queryset.filter(id=pk).first() if pk else None
    if row is None:
        raise ValidationError(f"Esa {label} no existe")
    return row


def _close_blocker(visit: ServiceVisit) -> str | None:
    """What `Technique.close_requirement`/`evidence_only` ask for, checked
    generically so `services` never has to import the optional module that
    owns the rule."""
    technique = visit.service_order.technique
    if technique.close_requirement == "plan_required":
        from modules.media.infrastructure.models import MediaAsset

        has_plan = MediaAsset.objects.filter(
            company_id=visit.company_id, owner_type="visit", owner_id=visit.id,
            kind="topography_plan",
        ).exists()
        if not has_plan:
            return "Debes subir el plano antes de cerrar la visita"

    if technique.evidence_only:
        from modules.diagnostics.infrastructure.models import EquipmentLogEntry
        from modules.media.infrastructure.models import MediaAsset

        has_photo = MediaAsset.objects.filter(
            company_id=visit.company_id, owner_type="visit", owner_id=visit.id,
        ).exists()
        if not has_photo:
            return "Debes subir al menos una foto antes de cerrar la visita"
        has_conclusion = EquipmentLogEntry.objects.filter(
            company_id=visit.company_id, service_visit_id=visit.id, entry_type="conclusion",
        ).exists()
        if not has_conclusion:
            return "Debes escribir una conclusión antes de cerrar la visita"
    return None
