"""The service ledger's queries: which orders match, and what they add up to."""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Count, Q, QuerySet

from modules.security.domain.actor import Role, behaviour_of
from modules.services.domain.order_filter import OrderFilter
from modules.services.infrastructure.models import ServiceOrder, ServiceVisit

ANALYST_BEHAVIOURS = frozenset({Role.ENGINEER, Role.COMPANY_ADMIN})


@dataclass(frozen=True, slots=True)
class OrderTotals:
    orders: int
    visits: int


def orders_matching(company_id: int, wanted: OrderFilter) -> QuerySet[ServiceOrder]:
    queryset = (
        ServiceOrder.objects.for_company(company_id)
        .select_related("technique", "plant", "provider", "lead_analyst", "supervisor", "standard")
        .annotate(visit_count=Count("visits", distinct=True))
        .order_by("-scheduled_from", "-id")
    )
    if wanted.text:
        text = wanted.text
        queryset = queryset.filter(
            Q(code__icontains=text)
            | Q(client_work_order__icontains=text)
            | Q(technique__name__icontains=text)
            | Q(provider__name__icontains=text)
            | Q(lead_analyst__first_name__icontains=text)
            | Q(lead_analyst__last_name__icontains=text)
        )
    if wanted.technique:
        queryset = queryset.filter(technique__code=wanted.technique)
    if wanted.status:
        queryset = queryset.filter(status=wanted.status)
    if wanted.date_from:
        queryset = queryset.filter(scheduled_to__gte=wanted.date_from)
    if wanted.date_to:
        queryset = queryset.filter(scheduled_from__lte=wanted.date_to)
    return queryset


def totals_of(queryset: QuerySet[ServiceOrder]) -> OrderTotals:
    """Over the whole filtered set, never the page: the totals used to sum the
    25 rows on screen while "Órdenes" counted all of them."""
    visits = ServiceVisit.objects.filter(service_order__in=queryset.values("id")).count()
    return OrderTotals(orders=queryset.count(), visits=visits)


def analysts_of(company_id: int) -> list[dict]:
    """People who can lead a service: engineers and administrators."""
    from modules.security.models import Membership

    memberships = (
        Membership.objects.filter(company_id=company_id, user__is_active=True)
        .select_related("user", "role")
        .order_by("user__first_name", "user__last_name")
    )
    return [
        {"id": row.user_id, "name": row.user.get_full_name()}
        for row in memberships
        if behaviour_of(row.role.base_role or row.role.code) in ANALYST_BEHAVIOURS
    ]

