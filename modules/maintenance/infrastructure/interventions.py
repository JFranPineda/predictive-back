"""Latest closed work record per train, in the same shape `services` uses for
visits (V3-07: a maintenance record counts as touching the train too)."""

from __future__ import annotations

from collections.abc import Iterable

from django.db.models import OuterRef, Subquery

from modules.assets.models import AssetGroup
from modules.maintenance.models import WorkRecord
from modules.services.domain.intervention import Intervention

WORK_TYPE_NAMES = dict(WorkRecord.WORK_TYPES)


def last_work_records(company_id: int, group_ids: Iterable[int]) -> dict[int, Intervention]:
    ids = list(group_ids)
    if not ids:
        return {}
    newest = (
        WorkRecord.objects.filter(asset_group_id=OuterRef("pk"), is_closed=True)
        .order_by("-ended_at", "-id")
        .values("id")[:1]
    )
    latest_ids = dict(
        AssetGroup.objects.for_company(company_id)
        .filter(id__in=ids)
        .annotate(record_id=Subquery(newest))
        .exclude(record_id=None)
        .values_list("id", "record_id")
    )
    rows = WorkRecord.objects.filter(id__in=latest_ids.values()).prefetch_related("responsibles__user")
    by_id = {row.id: row for row in rows}
    return {
        group_id: _intervention(by_id[record_id])
        for group_id, record_id in latest_ids.items()
        if record_id in by_id
    }


def _intervention(row: WorkRecord) -> Intervention:
    who = next(
        (r.external_name or (r.user.get_full_name() if r.user else "") for r in row.responsibles.all()),
        "",
    )
    what = " / ".join(WORK_TYPE_NAMES.get(code, code) for code in row.work_types)
    return Intervention(at=row.ended_at, what=what or "Mantenimiento", who=who)
