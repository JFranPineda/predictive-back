"""Trains as the unit of the assets list (V3-05).

A plant is read by train — motor and pump together — so the list is one row
per train with its machines inside. Filters keep the rule the ticket set: a
train is listed if any of its machines matches.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from django.db.models import Prefetch, Q

from modules.assets.domain.group_status import StatusView, effective_status, group_status
from modules.assets.infrastructure.models import AssetGroup, Equipment


@dataclass(frozen=True, slots=True)
class OverviewFilter:
    text: str = ""
    area: str = ""
    kind: str = ""
    equipment_type: str = ""
    status: str = ""


@dataclass(frozen=True, slots=True)
class GroupOverview:
    group: AssetGroup
    equipments: list[Equipment]
    status: StatusView


def train_overview(
    company_id: int, area_ids: Iterable[int] | None, wanted: OverviewFilter, language: str
) -> list[GroupOverview]:
    machines = Equipment.objects.select_related(
        "condition_status", "availability_status", "asset_group__sector__area", "asset_group__kind",
    ).order_by("order_in_group", "id")
    groups = (
        AssetGroup.objects.for_company(company_id)
        .select_related("sector__area", "kind")
        .prefetch_related(Prefetch("equipments", queryset=machines))
        .order_by("name", "id")
    )
    if area_ids is not None:
        groups = groups.filter(sector__area_id__in=list(area_ids))
    if wanted.area:
        groups = groups.filter(sector__area_id=wanted.area)
    if wanted.kind:
        groups = groups.filter(kind__code=wanted.kind)
    if wanted.equipment_type:
        groups = groups.filter(equipments__equipment_type=wanted.equipment_type)
    if wanted.text:
        text = wanted.text
        groups = groups.filter(
            Q(name__icontains=text) | Q(code__icontains=text)
            | Q(equipments__client_tag__icontains=text) | Q(equipments__asset_code__icontains=text)
            | Q(equipments__name__icontains=text)
        )
    rows = []
    for group in groups.distinct():
        equipments = list(group.equipments.all())
        effective = [_effective(machine, language) for machine in equipments]
        if wanted.status and wanted.status not in {status.code for status in effective}:
            continue
        rows.append(GroupOverview(group=group, equipments=equipments, status=group_status(effective)))
    return rows


def effective_of(machine: Equipment, language: str) -> StatusView:
    return _effective(machine, language)


def _effective(machine: Equipment, language: str) -> StatusView:
    return effective_status(_view(machine.condition_status, language),
                            _view(machine.availability_status, language))


def _view(status, language: str) -> StatusView | None:
    if status is None:
        return None
    return StatusView(
        code=status.code, name=status.translated("name", language), color=status.color,
        severity=status.severity, is_condition=status.kind == "condition", measurable=status.measurable,
    )
