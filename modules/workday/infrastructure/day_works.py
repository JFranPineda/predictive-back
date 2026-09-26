"""The day's works (F3-02), built from what the day already recorded: the
service visits and, when the module is installed, the correctivos."""

from __future__ import annotations

from datetime import timedelta

from modules.workday.domain.rules import Work, day_works

WORK_TYPES = {
    "bearing_change": "Cambio de rodamiento",
    "alignment": "Alineamiento",
    "balancing": "Balanceo",
    "other": "Otro",
}


def works_of(workday) -> list[Work]:
    return day_works([*_visits(workday), *_maintenance(workday)])


def _visits(workday) -> list[Work]:
    from modules.services.models import ServiceVisit

    visits = (
        ServiceVisit.objects.for_company(workday.company_id)
        .filter(service_order__plant_id=workday.plant_id, visited_at__date=workday.date)
        .select_related("service_order__technique", "equipment__asset_group")
        .prefetch_related("participants__user")
    )
    return [
        Work(
            kind="visit",
            id=visit.id,
            service=visit.service_order.technique.name,
            order=visit.service_order.code,
            group=visit.equipment.asset_group.name,
            equipment=visit.equipment.name,
            people=tuple(p.user.get_full_name() for p in visit.participants.all()),
            started_at=visit.visited_at,
            ended_at=(
                visit.visited_at + timedelta(minutes=visit.duration_min) if visit.duration_min else None
            ),
        )
        for visit in visits
    ]


def _maintenance(workday) -> list[Work]:
    from modules.core.infrastructure.routing import installed_codes

    if "maintenance" not in installed_codes():
        return []
    from modules.maintenance.models import WorkRecord

    rows = (
        WorkRecord.objects.for_company(workday.company_id)
        .filter(asset_group__sector__area__plant_id=workday.plant_id, shift_date=workday.date)
        .select_related("asset_group", "equipment")
        .prefetch_related("responsibles__user")
    )
    return [
        Work(
            kind="maintenance",
            id=row.id,
            service=" · ".join(WORK_TYPES.get(code, code) for code in row.work_types) or "Mantenimiento",
            order=row.client_work_order,
            group=row.asset_group.name,
            equipment=row.equipment.name if row.equipment_id else "",
            people=tuple(str(r) for r in row.responsibles.all()),
            started_at=row.started_at,
            ended_at=row.ended_at,
        )
        for row in rows
    ]
