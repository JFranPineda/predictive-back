from __future__ import annotations

from django.db.models import Count
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.security.application.access import build_actor
from modules.security.domain.policies import VisitRef, can_edit_visit
from modules.services.models import ServiceOrder, ServiceVisit


class ServiceOrderListView(APIView):
    """The service ledger: what was ordered, when, by whom, and how much of it
    actually got measured."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        language = getattr(request, "language", "es")
        queryset = (
            ServiceOrder.objects.for_company(request.company_id)
            .select_related("technique", "plant", "lead_analyst", "supervisor")
            .annotate(
                visit_count=Count("visits", distinct=True),
                closed_count=Count("visits", filter=None, distinct=True),
            )
            .order_by("-scheduled_from")
        )
        if request.query_params.get("status"):
            queryset = queryset.filter(status=request.query_params["status"])

        paginator = PageNumberPagination()
        paginator.page_size = 25
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response([
            {
                "id": order.id,
                "code": order.code,
                "client_work_order": order.client_work_order,
                "technique_code": order.technique.code,
                "technique_name": order.technique.translated("name", language),
                "plant": order.plant.name,
                "scheduled_from": order.scheduled_from.isoformat(),
                "scheduled_to": order.scheduled_to.isoformat(),
                "status": order.status,
                "lead_analyst": order.lead_analyst.get_full_name() if order.lead_analyst else None,
                "supervisor": order.supervisor.get_full_name() if order.supervisor else None,
                "visit_count": order.visit_count,
                "open_count": order.visits.filter(is_closed=False).count(),
            }
            for order in page
        ])


class AuthorshipView(APIView):
    """Who performed each service, with the notes, conclusions and
    recommendations they wrote — each line keeping its own author."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        language = getattr(request, "language", "es")
        actor = build_actor(request.user, request.company_id)
        queryset = (
            ServiceVisit.objects.for_company(request.company_id)
            .select_related(
                "equipment__asset_group__sector__area",
                "service_order__technique",
                "availability_status",
            )
            .prefetch_related("participants__user", "log_entries__author")
            .order_by("-visited_at")
        )
        if actor.area_ids is not None:
            queryset = queryset.filter(
                equipment__asset_group__sector__area_id__in=actor.area_ids
            )
        performed_by = request.query_params.get("performed_by")
        if performed_by:
            queryset = queryset.filter(participants__user_id=performed_by)
        if request.query_params.get("equipment"):
            queryset = queryset.filter(equipment_id=request.query_params["equipment"])

        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(
            [_visit(visit, actor, language) for visit in page]
        )


def _visit(visit: ServiceVisit, actor, language: str) -> dict:
    area = visit.equipment.asset_group.sector.area
    participants = list(visit.participants.all())
    reference = VisitRef(
        id=visit.id,
        area_id=area.id,
        participant_ids=frozenset(p.user_id for p in participants),
        lead_analyst_id=next((p.user_id for p in participants if p.role == "lead_analyst"), None),
        is_closed=visit.is_closed,
        report_issued=False,
        visited_on=visit.visited_at.date(),
    )
    return {
        "visit_id": visit.id,
        "equipment_id": visit.equipment_id,
        "equipment_name": visit.equipment.name,
        "equipment_tag": visit.equipment.client_tag or visit.equipment.asset_code,
        "area_label": f"{area.code} - {area.name}",
        "technique_code": visit.service_order.technique.code,
        "technique_name": visit.service_order.technique.translated("name", language),
        "visited_at": visit.visited_at.isoformat(),
        "participants": [
            {
                "user_id": p.user_id,
                "full_name": p.user.get_full_name(),
                "initials": p.user.initials,
                "role": p.role,
                "is_external": p.user.is_external,
            }
            for p in participants
        ],
        "entries": [
            {
                "id": entry.id,
                "entry_type": entry.entry_type,
                "entry_date": entry.entry_date.isoformat(),
                "text": entry.text,
                "author_id": entry.author_id,
                "author_name": entry.author.get_full_name() if entry.author else "",
            }
            for entry in visit.log_entries.all()
        ],
        "reading_count": visit.readings.count(),
        "media_count": 0,
        "is_closed": visit.is_closed,
        "report_issued": False,
        "can_edit": can_edit_visit(actor, reference),
    }
