"""The rows the record of values owes a train before any round read them.

A fixed table (`Magnitude.in_record`) shows on every train its service
measures: velocity, acceleration, envelope, temperature, ultrasound level and
wall thickness, as the customer's report always carries them. Its rows are
the points each machine's reading plan reads it on (V3-11's opt-in included),
for the services the train's rounds already use.
"""

from __future__ import annotations

from modules.measurements.infrastructure.models import Technique
from modules.measurements.infrastructure.point_plan import magnitude_plan


def planned_fixed(equipments, technique_ids) -> list[tuple[object, object]]:
    """(point, magnitude) pairs of fixed tables, machine by machine."""
    techniques = list(Technique.objects.filter(id__in=technique_ids))
    return [
        (point, magnitude)
        for equipment in equipments
        for technique in techniques
        for point, magnitude in magnitude_plan(equipment, technique)
        if magnitude.in_record
    ]
