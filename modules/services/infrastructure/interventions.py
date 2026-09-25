"""Latest service visit per train, in one query per page of trains."""

from __future__ import annotations

from collections.abc import Iterable

from django.db.models import OuterRef, Subquery

from modules.assets.models import AssetGroup
from modules.services.domain.intervention import Intervention
from modules.services.infrastructure.models import ServiceVisit


def last_visits(company_id: int, group_ids: Iterable[int], language: str) -> dict[int, Intervention]:
    ids = list(group_ids)
    if not ids:
        return {}
    newest = (
        ServiceVisit.objects.filter(equipment__asset_group_id=OuterRef("pk"))
        .order_by("-visited_at", "-id")
        .values("id")[:1]
    )
    latest_ids = dict(
        AssetGroup.objects.for_company(company_id)
        .filter(id__in=ids)
        .annotate(visit_id=Subquery(newest))
        .exclude(visit_id=None)
        .values_list("id", "visit_id")
    )
    visits = (
        ServiceVisit.objects.filter(id__in=latest_ids.values())
        .select_related("service_order__technique", "service_order__lead_analyst")
        .prefetch_related("participants__user")
    )
    by_visit = {visit.id: visit for visit in visits}
    return {
        group_id: _intervention(by_visit[visit_id], language)
        for group_id, visit_id in latest_ids.items()
        if visit_id in by_visit
    }


def _intervention(visit: ServiceVisit, language: str) -> Intervention:
    lead = next((p.user for p in visit.participants.all() if p.role == "lead_analyst"), None)
    lead = lead or visit.service_order.lead_analyst
    return Intervention(
        at=visit.visited_at,
        what=visit.service_order.technique.translated("name", language),
        who=lead.get_full_name() if lead else "",
    )
