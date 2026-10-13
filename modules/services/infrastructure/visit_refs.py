"""The policy view of a visit, built from the ORM in one place.

Every write path — readings, log entries, participants, operating data, media —
asks the same question: may this actor touch this visit? The answer needs the
same handful of facts each time, so they are gathered here instead of every
module reaching into this module's views for a private helper.
"""

from __future__ import annotations

from collections.abc import Iterable

from modules.security.domain.policies import VisitRef
from modules.services.infrastructure.models import ServiceVisit


def visit_ref(visit: ServiceVisit) -> VisitRef:
    participants = list(visit.participants.all())
    return VisitRef(
        id=visit.id,
        area_id=visit.equipment.asset_group.sector.area_id,
        participant_ids=frozenset(p.user_id for p in participants),
        lead_analyst_id=next((p.user_id for p in participants if p.role == "lead_analyst"), None),
        is_closed=visit.is_closed,
        report_issued=False,
        visited_on=visit.visited_at.date() if visit.visited_at else None,
    )


def visit_refs(company_id: int, visit_ids: Iterable[int]) -> dict[int, VisitRef]:
    """One query for a whole page of media, never one per tile."""
    ids = {int(visit_id) for visit_id in visit_ids if visit_id}
    if not ids:
        return {}
    visits = (
        ServiceVisit.objects.for_company(company_id)
        .filter(id__in=ids)
        .select_related("equipment__asset_group__sector")
        .prefetch_related("participants")
    )
    return {visit.id: visit_ref(visit) for visit in visits}


def train_of(equipment):
    """The machines measured together with this one, in the train's order.
    Retired ones are not measured any more."""
    from modules.assets.models import Equipment

    return Equipment.objects.filter(
        asset_group_id=equipment.asset_group_id, retired_at__isnull=True
    ).order_by("order_in_group", "id")


def train_visits(visit: ServiceVisit) -> list[dict]:
    """Each machine of the visit's train with its visit on the same order, if
    it has one: the round is one train, the visits are one per machine."""
    machines = list(train_of(visit.equipment))
    visits = dict(
        ServiceVisit.objects.filter(
            service_order_id=visit.service_order_id, equipment__in=machines
        ).order_by("id").values_list("equipment_id", "id")
    )
    return [
        {
            "equipment_id": machine.id,
            "tag": machine.client_tag or machine.asset_code,
            "name": machine.name,
            "visit_id": visit.id if machine.id == visit.equipment_id else visits.get(machine.id),
        }
        for machine in machines
    ]
