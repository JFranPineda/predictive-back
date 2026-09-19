"""The failure catalogue, and what each service found."""

from __future__ import annotations

from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.diagnostics.models import FaultMode
from modules.security.application.access import build_actor
from modules.security.domain.policies import can_write_log_entry
from modules.services.interfaces.visit_views import _load, _reference


class FaultModeListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        language = getattr(request, "language", "es")
        queryset = FaultMode.objects.for_company(request.company_id).filter(is_active=True)
        if request.query_params.get("technique"):
            # Each service reports its own vocabulary: a thermography visit
            # has no business offering "desalineamiento".
            queryset = queryset.filter(technique_code=request.query_params["technique"])
        return Response([
            {
                "id": row.id,
                "code": row.code,
                "name": row.translated("name", language),
                "technique_code": row.technique_code,
                "signature": row.typical_signature,
                "reference": row.iso_reference,
            }
            for row in queryset.order_by("name")
        ])

    def post(self, request):
        actor = build_actor(request.user, request.company_id)
        if not actor.has("diagnostics.close_recommendation"):
            raise PermissionDenied("Falta el permiso para gestionar el catálogo")
        name = (request.data.get("name") or "").strip()
        if not name:
            raise ValidationError("El nombre es obligatorio")
        code = _slug(request.data.get("code") or name)
        if FaultMode.objects.for_company(request.company_id).filter(code=code).exists():
            raise ValidationError(f"Ya existe el modo de falla '{code}'")
        fault = FaultMode.objects.create(
            company_id=request.company_id, code=code, name=name,
            technique_code=(request.data.get("technique_code") or "").strip(),
            typical_signature=(request.data.get("signature") or "").strip(),
            iso_reference=(request.data.get("reference") or "").strip(),
            translations={"name": {"es": name}},
        )
        return Response({"id": fault.id, "code": fault.code, "name": fault.name}, status=201)


class FaultModeDetailView(APIView):
    """The catalogue is the customer's, so it has to be correctable.

    A fault mode a visit already reported is deactivated, never destroyed:
    deleting it would take the finding out of a report that was signed.
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request, fault_id: int):
        fault = _fault(request, fault_id)
        _may_manage(request)
        name = (request.data.get("name") or "").strip()
        if name:
            fault.name = name
            fault.translations = {
                **fault.translations,
                "name": {**(fault.translations.get("name") or {}), "es": name},
            }
        if "technique_code" in request.data:
            fault.technique_code = (request.data.get("technique_code") or "").strip()
        if "signature" in request.data:
            fault.typical_signature = (request.data.get("signature") or "").strip()
        if "reference" in request.data:
            fault.iso_reference = (request.data.get("reference") or "").strip()
        if "is_active" in request.data:
            fault.is_active = bool(request.data["is_active"])
        fault.save()
        language = getattr(request, "language", "es")
        return Response({
            "id": fault.id, "code": fault.code, "name": fault.translated("name", language),
            "technique_code": fault.technique_code, "signature": fault.typical_signature,
            "reference": fault.iso_reference, "is_active": fault.is_active,
        })

    def delete(self, request, fault_id: int):
        fault = _fault(request, fault_id)
        _may_manage(request)
        used = fault.visits.count()
        if used:
            fault.is_active = False
            fault.save(update_fields=["is_active"])
            return Response({"id": fault.id, "is_active": False, "deactivated": True,
                             "reason": f"lo reportan {used} visita(s)"})
        fault.delete()
        return Response(status=204)


def _fault(request, fault_id: int):
    row = FaultMode.objects.for_company(request.company_id).filter(id=fault_id).first()
    if row is None:
        raise ValidationError("Ese modo de falla no existe")
    return row


def _may_manage(request) -> None:
    actor = build_actor(request.user, request.company_id)
    if not actor.has("diagnostics.close_recommendation"):
        raise PermissionDenied("Falta el permiso para gestionar el catálogo")


class VisitFaultsView(APIView):
    """What this service found. Optional, and one or several."""

    permission_classes = [IsAuthenticated]

    def put(self, request, visit_id: int):
        visit = _load(request, visit_id)
        actor = build_actor(request.user, request.company_id)
        if not can_write_log_entry(actor, _reference(visit)):
            raise PermissionDenied("Esta visita no es tuya o ya está cerrada")

        codes = list(request.data.get("codes") or [])
        technique = visit.service_order.technique.code
        faults = list(
            FaultMode.objects.for_company(request.company_id).filter(code__in=codes)
        )
        wrong = [
            fault.code
            for fault in faults
            if fault.technique_code and fault.technique_code != technique
        ]
        if wrong:
            raise ValidationError(
                f"Estos modos de falla no pertenecen a {technique}: {', '.join(wrong)}"
            )
        unknown = set(codes) - {fault.code for fault in faults}
        if unknown:
            raise ValidationError(f"Modos de falla desconocidos: {', '.join(sorted(unknown))}")

        visit.fault_modes.set(faults)
        return Response({"codes": sorted(fault.code for fault in faults)})


def _slug(value: str) -> str:
    cleaned = "".join(c if c.isalnum() else "_" for c in (value or "").strip().lower())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "falla"
