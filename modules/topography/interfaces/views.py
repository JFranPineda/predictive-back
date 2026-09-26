"""Topografía: one row per plant element per visit — level and parallelism,
against the plan the visit already carries as a `topography_plan` image.

No verdict here (Q11 in the ticket: tolerances aren't confirmed yet). The
value and the analyst's own conclusion are what the visit records.
"""

from __future__ import annotations

from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.security.application.access import build_actor
from modules.security.domain.policies import can_edit_visit
from modules.services.infrastructure.visit_refs import visit_ref
from modules.topography.models import TopographyElementReading

FIELDS = ("level_h", "level_v", "parallel_h", "parallel_v")


class TopographyElementListView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        actor = build_actor(request.user, request.company_id)
        if not actor.has("topography.view"):
            raise PermissionDenied("Falta el permiso topography.view")
        visit_id = request.query_params.get("visit")
        if not visit_id:
            raise ValidationError("Falta el parámetro 'visit'")
        rows = TopographyElementReading.objects.for_company(request.company_id).filter(
            service_visit_id=visit_id
        )
        return Response([_payload(row) for row in rows])

    def post(self, request):
        visit = _visit(request, request.data.get("service_visit"))
        actor = build_actor(request.user, request.company_id)
        if not can_edit_visit(actor, visit_ref(visit)):
            raise PermissionDenied("Esta visita no es tuya o ya está cerrada")

        label = (request.data.get("element_label") or "").strip()
        if not label:
            raise ValidationError("El elemento necesita su número del plano")

        row = TopographyElementReading.objects.create(
            company_id=request.company_id, asset_group_id=visit.equipment.asset_group_id,
            service_visit=visit, element_label=label,
            observation=(request.data.get("observation") or "").strip(),
            created_by=request.user,
            **{field: request.data.get(field) for field in FIELDS if field in request.data},
        )
        return Response(_payload(row), status=201)


class TopographyElementDetailView(APIView):
    permission_classes = (IsAuthenticated,)

    def patch(self, request, reading_id: int):
        row = _writable_row(request, reading_id)
        if "element_label" in request.data:
            label = (request.data["element_label"] or "").strip()
            if not label:
                raise ValidationError("El elemento necesita su número del plano")
            row.element_label = label
        if "observation" in request.data:
            row.observation = (request.data["observation"] or "").strip()
        for field in FIELDS:
            if field in request.data:
                setattr(row, field, request.data[field])
        row.save()
        return Response(_payload(row))

    def delete(self, request, reading_id: int):
        row = _writable_row(request, reading_id)
        row.delete()
        return Response(status=204)


class TopographyHistoryView(APIView):
    """The element's trend across visits (AC-02): every reading it ever got
    on this train, dated, regardless of which visit wrote it."""

    permission_classes = (IsAuthenticated,)

    def get(self, request):
        actor = build_actor(request.user, request.company_id)
        if not actor.has("topography.view"):
            raise PermissionDenied("Falta el permiso topography.view")
        group_id = request.query_params.get("group")
        element = (request.query_params.get("element") or "").strip()
        if not group_id or not element:
            raise ValidationError("Faltan los parámetros 'group' y 'element'")

        rows = (
            TopographyElementReading.objects.for_company(request.company_id)
            .filter(asset_group_id=group_id, element_label=element)
            .select_related("service_visit")
            .order_by("service_visit__visited_at")
        )
        return Response(
            [
                {**_payload(row), "visited_at": row.service_visit.visited_at.isoformat()}
                for row in rows
            ]
        )


def _visit(request, visit_id):
    from modules.services.infrastructure.models import ServiceVisit

    visit = (
        ServiceVisit.objects.for_company(request.company_id)
        .select_related("equipment__asset_group")
        .filter(id=visit_id)
        .first()
    )
    if visit is None:
        raise ValidationError("Esa visita no existe")
    return visit


def _writable_row(request, reading_id: int) -> TopographyElementReading:
    row = (
        TopographyElementReading.objects.for_company(request.company_id)
        .select_related("service_visit")
        .filter(id=reading_id)
        .first()
    )
    if row is None:
        raise ValidationError("Ese elemento no existe")
    actor = build_actor(request.user, request.company_id)
    if not can_edit_visit(actor, visit_ref(row.service_visit)):
        raise PermissionDenied("Esta visita no es tuya o ya está cerrada")
    return row


def _payload(row: TopographyElementReading) -> dict:
    return {
        "id": row.id,
        "service_visit_id": row.service_visit_id,
        "element_label": row.element_label,
        "level_h": _decimal_str(row.level_h),
        "level_v": _decimal_str(row.level_v),
        "parallel_h": _decimal_str(row.parallel_h),
        "parallel_v": _decimal_str(row.parallel_v),
        "observation": row.observation,
    }


def _decimal_str(value) -> str | None:
    return None if value is None else str(value)
