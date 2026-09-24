from __future__ import annotations

from datetime import timedelta

from django.db.models import Max
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.assets.models import Equipment
from modules.summaries.domain.rollup import Driver, EquipmentStatus, by_technique
from modules.thresholds.domain.entities import Status, StatusKind


class PlantSummaryView(APIView):
    """The traffic light. One per technique, because a pump can be in alarm on
    vibration and fine on thermography."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        language = getattr(request, "language", "es")
        queryset = (
            Equipment.objects.for_company(request.company_id)
            .select_related(
                "asset_group__sector__area", "asset_group__kind",
                "condition_status", "availability_status",
            )
        )
        if request.query_params.get("plant"):
            queryset = queryset.filter(
                asset_group__sector__area__plant_id=request.query_params["plant"]
            )

        from modules.security.application.access import allowed_area_ids

        areas = allowed_area_ids(request.user, request.company_id)
        if areas is not None:
            queryset = queryset.filter(asset_group__sector__area_id__in=areas)

        equipments = list(queryset)
        # One monitoring cycle back. A machine measured four months ago is not
        # green today, it is uncovered, and the traffic light has to say so.
        days = int(request.query_params.get("days") or 45)
        ids = [item.id for item in equipments]
        served = _route_membership(request.company_id, ids)
        worst = _worst_by_technique(request.company_id, ids, days)
        drivers = _drivers(request.company_id, equipments, days)
        statuses = _condition_statuses(request.company_id, language)

        rows = [
            _to_domain(
                item, language, technique,
                statuses.get(worst.get((item.id, technique))),
                drivers.get((item.id, technique)),
            )
            for item in equipments
            for technique in served.get(item.id, ())
        ]
        summaries = by_technique(rows)
        techniques = _technique_names(language)

        return Response([
            {
                "technique_code": code,
                "technique_name": techniques.get(code, code),
                "nodes": [_node(node) for node in nodes],
            }
            for code, nodes in summaries.items()
        ])


def _route_membership(company_id: int, ids: list[int]) -> dict[int, list[str]]:
    """Which services each machine is actually on.

    A transformer is not missing from the vibration round; it was never on it.
    Membership is "has ever been measured by this service", so a machine that
    the route skipped this month counts as uncovered instead of green.
    """
    from modules.measurements.models import Reading

    rows = (
        Reading.objects.for_company(company_id)
        .filter(point__equipment_id__in=ids)
        .values_list("point__equipment_id", "magnitude__technique__code")
        .distinct()
    )
    membership: dict[int, list[str]] = {}
    for equipment_id, technique in rows:
        membership.setdefault(equipment_id, []).append(technique)
    return membership


def _worst_by_technique(company_id: int, ids: list[int], days: int) -> dict:
    """The worst condition each machine reached per service, in one query.

    "Gana el peor" is the rule of the sheet, so the aggregate *is* the answer:
    no need to find the latest reading of every magnitude one by one.
    """
    from modules.measurements.models import Reading

    rows = (
        Reading.objects.for_company(company_id)
        .filter(
            point__equipment_id__in=ids,
            taken_at__gte=timezone.now() - timedelta(days=days),
            condition_status__isnull=False,
        )
        .values("point__equipment_id", "magnitude__technique__code")
        .annotate(worst=Max("condition_status__severity"))
    )
    found: dict[tuple[int, str], int] = {}
    for row in rows:
        key = (row["point__equipment_id"], row["magnitude__technique__code"])
        found[key] = max(found.get(key, 0), row["worst"])
    return found


def _condition_statuses(company_id: int, language: str) -> dict:
    from modules.thresholds.models import Status as StatusRow

    return {
        row.severity: _status(row, language)
        for row in StatusRow.objects.for_company(company_id).filter(kind="condition")
    }


def _drivers(company_id: int, equipments: list, days: int) -> dict:
    """The reading behind each machine's colour, per service.

    The one that earned the worst verdict; among equals, the most extreme in
    its own magnitude's direction. That is the number the report prints next
    to the bar, and the reason the tag beside it is worth walking to.
    """
    from modules.measurements.models import Reading, Technique

    # The magnitude each report leads with. Everything else is a candidate
    # only when the headline was not measured.
    headline = {
        row.code: row.headline_magnitude
        for row in Technique.objects.exclude(headline_magnitude="")
    }
    tags = {item.id: (item.client_tag or item.asset_code) for item in equipments}
    rows = (
        Reading.objects.for_company(company_id)
        .filter(
            point__equipment_id__in=list(tags),
            taken_at__gte=timezone.now() - timedelta(days=days),
            value__isnull=False,
        )
        .values_list(
            "point__equipment_id",
            "magnitude__technique__code",
            "magnitude__code",
            "magnitude__default_unit__code",
            "magnitude__higher_is_worse",
            "value",
            "condition_status__severity",
            "operator__first_name",
            "operator__last_name",
            "taken_at",
            "created_at",
        )
    )

    best: dict[tuple[int, str], tuple[tuple[int, int], Driver]] = {}
    for (
        equipment_id, technique, magnitude, unit, higher, value, severity,
        first_name, last_name, taken_at, created_at,
    ) in rows:
        key = (equipment_id, technique)
        # A headline reading outranks any other, however alarming the other
        # looks: 16 dB of friction is not what decides a roll's thickness.
        rank = (1 if magnitude == headline.get(technique) else 0, severity or 0)
        current = best.get(key)
        candidate = Driver(
            value=float(value),
            unit=unit,
            magnitude_code=magnitude,
            higher_is_worse=higher,
            equipment_id=equipment_id,
            equipment_tag=tags[equipment_id],
            recorded_by=f"{first_name or ''} {last_name or ''}".strip(),
            recorded_at=created_at.isoformat() if created_at else None,
            measured_at=taken_at.isoformat() if taken_at else None,
        )
        if current is None or rank > current[0] or (
            rank == current[0] and _beats(candidate, current[1])
        ):
            best[key] = (rank, candidate)
    return {key: driver for key, (_, driver) in best.items()}


def _beats(candidate: Driver, held: Driver) -> bool:
    """Only compare like with like: mm/s never outranks gE."""
    if candidate.magnitude_code != held.magnitude_code:
        return candidate.higher_is_worse and not held.higher_is_worse
    return (
        candidate.value > held.value
        if candidate.higher_is_worse
        else candidate.value < held.value
    )


def _to_domain(
    item: Equipment, language: str, technique: str, condition, driver=None
) -> EquipmentStatus:
    area = item.asset_group.sector.area
    return EquipmentStatus(
        equipment_id=item.id,
        name=item.name,
        area_id=area.id,
        area_label=f"{area.code} - {area.name}",
        sector_id=item.asset_group.sector_id,
        sector_label=item.asset_group.sector.name,
        asset_group_id=item.asset_group_id,
        asset_group_label=item.asset_group.name,
        technique_code=technique,
        condition=condition,
        availability=_status(item.availability_status, language),
        driver=driver,
    )


def _status(row, language: str) -> Status | None:
    if row is None:
        return None
    return Status(
        code=row.code, name=row.translated("name", language), kind=StatusKind(row.kind),
        severity=row.severity, color=row.color, requires_action=row.requires_action,
        is_terminal=row.is_terminal, measurable=row.measurable,
    )


def _node(node) -> dict:
    return {
        "key": node.key,
        "label": node.label,
        "level": node.level,
        "total": node.total,
        "evaluated": node.evaluated,
        "coverage": node.coverage,
        "worst": _status_payload(node.worst),
        "driver": _driver_payload(node.driver),
        "counts": [
            {"status": _status_payload(count.status), "count": count.count}
            for count in node.counts
        ],
        "children": [_node(child) for child in node.children],
    }


def _driver_payload(driver) -> dict | None:
    if driver is None:
        return None
    return {
        "value": driver.value,
        "unit": driver.unit,
        "magnitude_code": driver.magnitude_code,
        "higher_is_worse": driver.higher_is_worse,
        "equipment_id": driver.equipment_id,
        "equipment_tag": driver.equipment_tag,
        "recorded_by": driver.recorded_by,
        "recorded_at": driver.recorded_at,
        "measured_at": driver.measured_at,
    }


def _status_payload(status: Status) -> dict:
    return {
        "code": status.code, "name": status.name, "kind": status.kind.value,
        "severity": status.severity, "color": status.color,
        "measurable": status.measurable, "requires_action": status.requires_action,
    }


def _technique_names(language: str) -> dict[str, str]:
    from modules.measurements.models import Technique

    return {row.code: row.translated("name", language) for row in Technique.objects.all()}
