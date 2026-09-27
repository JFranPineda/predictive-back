"""What the thickness sheet, the journals and the group report share: the
permission check, the order, the group's rollers, a roller's visit and the
edit lock."""

from __future__ import annotations

from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from modules.core.infrastructure.edit_locks import edit_lock
from modules.security.domain.policies import can_record_reading
from modules.security.infrastructure.access import build_actor
from modules.services.infrastructure.visit_refs import visit_ref
from modules.ut_rollers.domain.rollers import TECHNIQUE


def require(request, permission: str):
    actor = build_actor(request.user, request.company_id)
    if not actor.has(permission):
        raise PermissionDenied(f"Falta el permiso {permission}")
    return actor


def find_order(request, order_id: int):
    from modules.services.models import ServiceOrder

    order = (
        ServiceOrder.objects.for_company(request.company_id)
        .select_related("technique")
        .filter(id=order_id)
        .first()
    )
    if order is None:
        raise ValidationError("Esa orden no existe")
    if order.technique.code != TECHNIQUE:
        raise ValidationError("Esa orden no es de UT en rodillos")
    return order


def rollers_of(request, group_id: int):
    from modules.assets.models import Equipment

    actor = build_actor(request.user, request.company_id)
    rows = (
        Equipment.objects.for_company(request.company_id)
        .filter(asset_group_id=group_id, equipment_type="roller", retired_at__isnull=True)
        .select_related("asset_group__sector")
        .prefetch_related("points")
        .order_by("order_in_group", "id")
    )
    if actor.area_ids is not None:
        rows = rows.filter(asset_group__sector__area_id__in=actor.area_ids)
    return list(rows)


def visit_for(request, actor, order, roller):
    from modules.services.models import ServiceVisit, VisitParticipant

    visit = (
        ServiceVisit.objects.for_company(request.company_id)
        .filter(service_order=order, equipment=roller)
        .select_related("equipment__asset_group__sector")
        .prefetch_related("participants")
        .order_by("-visited_at", "-id")
        .first()
    )
    if visit is not None:
        if not can_record_reading(actor, visit_ref(visit)):
            raise PermissionDenied(f"No puedes registrar lecturas en {roller.name}")
        return visit
    if not actor.may_reach_area(roller.asset_group.sector.area_id):
        raise PermissionDenied("Ese conjunto está fuera de tu alcance")
    visit = ServiceVisit.objects.create(
        company_id=request.company_id,
        service_order=order,
        equipment=roller,
        visited_at=timezone.now(),
    )
    VisitParticipant.objects.create(visit=visit, user=request.user, role="lead_analyst")
    return visit


def lock_of(request, order, group_id: int) -> str | None:
    """Why this group's data of this order is read-only right now (Q19)."""
    return edit_lock(request, asset_group_id=group_id, order_id=order.id)
