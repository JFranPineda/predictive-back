"""Mediciones: the trains a service is measured on (V3-06, V3-07).

One row per train, the points the chosen service reads on it, and the last
time the train was touched by anyone.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from django.db.models import Count

from modules.assets.infrastructure.group_overview import GroupOverview, OverviewFilter, train_overview
from modules.maintenance.infrastructure.interventions import last_work_records
from modules.measurements.infrastructure.models import Reading
from modules.services.domain.intervention import Intervention, latest
from modules.services.infrastructure.interventions import last_visits

ORDERS = ("name", "last_intervention")


@dataclass(frozen=True, slots=True)
class TrainIndexRow:
    overview: GroupOverview
    measured_points: int
    last_intervention: Intervention | None


def train_index(
    company_id: int,
    area_ids: Iterable[int] | None,
    *,
    technique: str,
    text: str,
    language: str,
    order: str = "name",
) -> list[TrainIndexRow]:
    trains = train_overview(company_id, area_ids, OverviewFilter(text=text), language)
    measured = _measured_points(company_id, technique)
    trains = [train for train in trains if measured.get(train.group.id)]
    group_ids = [train.group.id for train in trains]
    visited = last_visits(company_id, group_ids, language)
    worked = last_work_records(company_id, group_ids)
    rows = [
        TrainIndexRow(
            train, measured[train.group.id],
            latest([visited.get(train.group.id), worked.get(train.group.id)]),
        )
        for train in trains
    ]
    if order == "last_intervention":
        # Newest first; trains never touched go last.
        rows.sort(key=lambda row: (row.last_intervention is None,
                                   -(row.last_intervention.at.timestamp() if row.last_intervention else 0)))
    return rows


def _measured_points(company_id: int, technique: str) -> dict[int, int]:
    """Points with at least one reading of the service, per train."""
    rows = (
        Reading.objects.for_company(company_id)
        .filter(magnitude__technique__code=technique)
        .values("point__equipment__asset_group_id")
        .annotate(points=Count("point_id", distinct=True))
    )
    return {row["point__equipment__asset_group_id"]: row["points"] for row in rows}
