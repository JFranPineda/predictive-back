"""Which visits a reader may open, for every view that takes one by id.

The same gap as the machines: a visit of an area out of the reader's reach
opened by its id. `can_view_visit` was written for this and nobody asked it.
"""

from __future__ import annotations

from modules.security.domain.policies import can_view_visit
from modules.security.infrastructure.access import build_actor
from modules.services.infrastructure.visit_refs import visit_ref


def find_visible_visit(request, visit_id):
    from modules.services.models import ServiceVisit

    visit = (
        ServiceVisit.objects.for_company(request.company_id)
        .select_related("equipment__asset_group__sector__area", "service_order")
        .prefetch_related("participants")
        .filter(id=visit_id)
        .first()
    )
    if visit is None:
        return None
    actor = build_actor(request.user, request.company_id)
    return visit if can_view_visit(actor, visit_ref(visit)) else None
