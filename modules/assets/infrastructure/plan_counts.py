"""What counts against the plan (V3-36).

A machine that was retired or deleted keeps its history — nothing with
readings is destroyed — so it cannot keep occupying a slot forever.
"""

from __future__ import annotations

from modules.assets.infrastructure.models import Equipment, Plant


def equipment_in_plan(company_id: int) -> int:
    return (
        Equipment.objects.for_company(company_id)
        .filter(retired_at__isnull=True)
        .exclude(availability_status__code="retired")
        .count()
    )


def plants_in_plan(company_id: int) -> int:
    return Plant.objects.for_company(company_id).count()
