"""The service ledger: what was ordered, when, executed by which company, and
how much of it actually got measured."""

from __future__ import annotations

from django.db import IntegrityError, transaction
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.licensing.infrastructure.context import current_alias
from modules.security.application.access import build_actor
from modules.security.domain.policies import can_change_order_status
from modules.services.domain.order_filter import order_filter_from
from modules.services.infrastructure.order_queries import analysts_of, orders_matching, totals_of
from modules.services.models import ServiceOrder, ServiceProvider

PAGE_SIZE = 25


class ServiceOrderListView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        language = getattr(request, "language", "es")
        queryset = orders_matching(request.company_id, order_filter_from(request.query_params))
        totals = totals_of(queryset)

        paginator = PageNumberPagination()
        paginator.page_size = PAGE_SIZE
        page = paginator.paginate_queryset(queryset, request, view=self)
        response = paginator.get_paginated_response([_order(order, language) for order in page])
        response.data["totals"] = {"orders": totals.orders, "visits": totals.visits}
        response.data["can_change_status"] = can_change_order_status(
            build_actor(request.user, request.company_id)
        )
        return response


def _order(order: ServiceOrder, language: str) -> dict:
    return {
        "id": order.id,
        "code": order.code,
        "client_work_order": order.client_work_order,
        "technique_code": order.technique.code,
        "technique_name": order.technique.translated("name", language),
        "plant": order.plant.name,
        "plant_id": order.plant_id,
        "scheduled_from": order.scheduled_from.isoformat(),
        "scheduled_to": order.scheduled_to.isoformat(),
        "status": order.status,
        "provider": _named(order.provider, order.provider.name if order.provider else ""),
        "lead_analyst": _named(
            order.lead_analyst, order.lead_analyst.get_full_name() if order.lead_analyst else ""
        ),
        "supervisor": order.supervisor.get_full_name() if order.supervisor else None,
        "visit_count": order.visit_count,
    }


def _named(row, name: str) -> dict | None:
    return {"id": row.id, "name": name} if row is not None else None


class ServiceProviderView(APIView):
    """The companies that execute services: a short catalogue per customer."""

    permission_classes = (IsAuthenticated,)

    def get(self, request):
        rows = ServiceProvider.objects.for_company(request.company_id)
        if request.query_params.get("active") == "1":
            rows = rows.filter(is_active=True)
        return Response([_provider(row) for row in rows])

    def post(self, request):
        _require_manage(request)
        name = (request.data.get("name") or "").strip()
        if not name:
            raise ValidationError("El nombre de la empresa es obligatorio")
        try:
            with transaction.atomic(using=current_alias()):
                provider = ServiceProvider.objects.create(
                    company_id=request.company_id, name=name,
                    tax_id=(request.data.get("tax_id") or "").strip(),
                )
        except IntegrityError as cause:
            raise ValidationError(f"Ya existe la empresa '{name}'") from cause
        return Response(_provider(provider), status=201)


class ServiceProviderDetailView(APIView):
    permission_classes = (IsAuthenticated,)

    def patch(self, request, provider_id: int):
        _require_manage(request)
        provider = ServiceProvider.objects.for_company(request.company_id).filter(id=provider_id).first()
        if provider is None:
            raise ValidationError("Esa empresa no existe")
        if "name" in request.data:
            provider.name = (request.data.get("name") or "").strip() or provider.name
        if "tax_id" in request.data:
            provider.tax_id = (request.data.get("tax_id") or "").strip()
        if "is_active" in request.data:
            # Deactivated, never deleted: past orders keep the company that did them.
            provider.is_active = bool(request.data["is_active"])
        provider.save()
        return Response(_provider(provider))


def _provider(row: ServiceProvider) -> dict:
    return {"id": row.id, "name": row.name, "tax_id": row.tax_id, "is_active": row.is_active,
            "order_count": row.orders.count()}


class AnalystListView(APIView):
    """Who can be named as the analyst of an order."""

    permission_classes = (IsAuthenticated,)

    def get(self, request):
        return Response(analysts_of(request.company_id))


def _require_manage(request) -> None:
    if not build_actor(request.user, request.company_id).has("services.manage_order"):
        raise PermissionDenied("Falta el permiso services.manage_order")
