"""The journals' tables and the results summary, for the screen and the report (Q15)."""

from __future__ import annotations

from modules.ut_rollers.domain.rollers import (
    SIDES,
    Finding,
    describe_indication,
    journal_state,
    results_summary,
)
from modules.ut_rollers.infrastructure.models import JournalInspection, UTIndication
from modules.ut_rollers.infrastructure.setup import KIND

MEASURES = ("diameter_mm", "external_length_mm", "total_length_mm")


def _plain(value) -> str | None:
    return None if value is None else format(value.normalize(), "f")


def order_findings(company_id: int, order, equipment_ids=None):
    """The order's journal findings: indications with a side, on the
    rollers of the order's visits."""
    rows = (
        UTIndication.objects.for_company(company_id)
        .filter(service_visit__service_order=order)
        .exclude(side="")
        .select_related("equipment__asset_group")
    )
    if equipment_ids is not None:
        rows = rows.filter(equipment_id__in=equipment_ids)
    return rows.order_by("equipment__order_in_group", "id")


def journal_sides(company_id: int, order, rollers) -> dict[str, list[dict]]:
    """Each side's detail table: per roller its measures, access, state and
    the findings on that side."""
    inspections = {
        (row.equipment_id, row.side): row
        for row in JournalInspection.objects.for_company(company_id).filter(
            service_order=order, equipment__in=rollers
        )
    }
    findings: dict[tuple[int, str], list] = {}
    for row in order_findings(company_id, order, [r.id for r in rollers]):
        findings.setdefault((row.equipment_id, row.side), []).append(row)
    sides = {}
    for side in SIDES:
        rows = []
        for roller in rollers:
            found = findings.get((roller.id, side), [])
            inspection = inspections.get((roller.id, side))
            descriptions = [describe_indication(f.kind, f.length_mm, f.depth_mm, f.notes) for f in found]
            access = inspection.access if inspection else "ok"
            note = inspection.access_note if inspection else ""
            written = inspection.state_text if inspection else ""
            rows.append(
                {
                    "equipment_id": roller.id,
                    "number": roller.order_in_group,
                    "name": roller.name,
                    "recorded": inspection is not None,
                    **{
                        field: _plain(getattr(inspection, field)) if inspection else None
                        for field in MEASURES
                    },
                    "access": access,
                    "access_note": note,
                    "state_text": written,
                    # Not recorded and nothing found: nothing to say yet.
                    "state": written
                    or (journal_state(access, note, descriptions) if inspection or found else ""),
                    "findings": [
                        {
                            "id": f.id,
                            "kind": f.kind,
                            "length_mm": _plain(f.length_mm),
                            "depth_mm": _plain(f.depth_mm),
                            "description": text,
                        }
                        for f, text in zip(found, descriptions, strict=True)
                    ],
                }
            )
        sides[side] = rows
    return sides


def results_of(company_id: int, order) -> list[dict]:
    """Groups in name order: every group of rollers with a journal row or a
    finding in this order."""
    from modules.assets.models import AssetGroup

    group_ids = set(
        JournalInspection.objects.for_company(company_id)
        .filter(service_order=order)
        .values_list("equipment__asset_group_id", flat=True)
    )
    found = list(order_findings(company_id, order))
    group_ids |= {row.equipment.asset_group_id for row in found}
    groups = list(
        AssetGroup.objects.for_company(company_id)
        .filter(id__in=group_ids, kind__code=KIND)
        .order_by("name")
        .values_list("name", flat=True)
    )
    return results_summary(
        groups,
        [
            Finding(
                group=row.equipment.asset_group.name,
                side=row.side,
                kind=row.kind,
                description=describe_indication(row.kind, row.length_mm, row.depth_mm, row.notes),
                roller=row.equipment.order_in_group,
            )
            for row in found
        ],
    )


def report_sections(company_id: int, order) -> dict:
    """What the END report adds for UT on rollers (Q15): the results summary,
    and per group its plan, the journals' detail tables, the conclusions,
    the recommendations and the photographic record. Images are returned as
    assets: the report embeds them."""
    from modules.assets.models import Equipment
    from modules.media.infrastructure.models import MediaAsset
    from modules.ut_rollers.infrastructure.models import RollerGroupReport

    reports = {
        row.asset_group_id: row
        for row in RollerGroupReport.objects.for_company(company_id)
        .filter(service_order=order)
        .select_related("asset_group", "plan_image")
    }
    journal_groups = set(
        JournalInspection.objects.for_company(company_id)
        .filter(service_order=order)
        .values_list("equipment__asset_group_id", flat=True)
    )
    groups = []
    for group_id in sorted(set(reports) | journal_groups):
        rollers = list(
            Equipment.objects.for_company(company_id)
            .filter(asset_group_id=group_id, equipment_type="roller", retired_at__isnull=True)
            .select_related("asset_group")
            .order_by("order_in_group", "id")
        )
        if not rollers and group_id not in reports:
            continue
        report = reports.get(group_id)
        sides = journal_sides(company_id, order, rollers) if group_id in journal_groups else {}
        groups.append(
            {
                "name": report.asset_group.name if report else rollers[0].asset_group.name,
                "plan": report.plan_image if report and report.plan_image_id else None,
                "conclusions": report.conclusions if report else "",
                "recommendations": report.recommendations if report else "",
                "photos": list(
                    MediaAsset.objects.for_company(company_id)
                    .filter(owner_type="ut_group_report", owner_id=report.id, kind="photo")
                    .order_by("created_at", "id")
                )
                if report
                else [],
                "journals": [
                    {"side": SIDES[side], "rows": [row for row in rows if row["recorded"] or row["findings"]]}
                    for side, rows in sides.items()
                    if any(row["recorded"] or row["findings"] for row in rows)
                ],
            }
        )
    groups.sort(key=lambda group: group["name"])
    return {"results": results_of(company_id, order), "groups": groups}
