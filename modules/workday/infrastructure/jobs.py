"""Today's services of a train, as the guard and the views ask about them."""

from __future__ import annotations

from datetime import date

from modules.workday.domain.rules import JobRef, job_allows


def allows(company_id: int, group_id: int, day: date, order_id: int | None = None) -> bool:
    """Whether a started, unclosed service of this train in that day's open
    workday lets someone fill its data."""
    from modules.workday.models import ServiceJob

    jobs = [
        JobRef(
            asset_group_id=row.asset_group_id,
            service_order_id=row.service_order_id,
            started=row.started_at is not None,
            closed=row.closed_at is not None,
        )
        for row in ServiceJob.objects.for_company(company_id).filter(
            workday__date=day,
            workday__closed_at__isnull=True,
            asset_group_id=group_id,
        )
    ]
    return job_allows(jobs, group_id, order_id)
