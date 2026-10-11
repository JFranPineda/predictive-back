"""Which machines a reader may see, for every view that takes one by id.

The lists were filtered by the reader's areas; the detail routes were not, so
a user narrowed to one area read any machine's trend, nameplate or gallery by
typing its id. Out of reach reads as not found: a 403 would confirm the
machine exists.
"""

from __future__ import annotations

from modules.security.infrastructure.access import build_actor


def visible_equipments(request, queryset):
    """`queryset` of Equipment, narrowed to what this reader may see."""
    actor = build_actor(request.user, request.company_id)
    if not actor.has("assets.view_equipment"):
        return queryset.none()
    if actor.area_ids is not None:
        queryset = queryset.filter(asset_group__sector__area_id__in=actor.area_ids)
    return queryset


def find_visible_equipment(request, equipment_id):
    from modules.assets.models import Equipment

    return visible_equipments(
        request,
        Equipment.objects.for_company(request.company_id)
        .select_related("asset_group__sector__area")
        .filter(id=equipment_id),
    ).first()
