"""Builds the evaluation context for one reading, in one place.

Three screens needed the same thing — the visit form, the record of values
and the workbook export — and each was assembling it slightly differently.
The machine class in particular is worked out here from the nameplate, so a
reading is never graded against a table that does not describe the machine.
"""

from __future__ import annotations

from modules.thresholds.domain.entities import Aggregation, EvaluationContext
from modules.thresholds.domain.services import classify_context
from modules.thresholds.infrastructure.repositories import standard_to_domain


def context_for(equipment, magnitude_code: str, aggregation: str, point_id: int | None = None):
    plate = getattr(equipment, "nameplate", None)
    standard = equipment.applied_standard

    context = EvaluationContext(
        magnitude_code=magnitude_code,
        aggregation=Aggregation(aggregation),
        point_id=point_id,
        equipment_id=equipment.id,
        equipment_type=equipment.equipment_type,
        asset_group_kind=equipment.asset_group.kind.code if equipment.asset_group.kind_id else None,
        machine_class=equipment.machine_class.code if equipment.machine_class_id else None,
        standard_code=standard.code if standard else None,
        rated_power_kw=float(plate.rated_power_kw)
        if plate and plate.rated_power_kw is not None
        else None,
        mounting=(plate.mounting or None) if plate else None,
    )
    if standard is None:
        return context
    return classify_context(context, standard_to_domain(standard))
