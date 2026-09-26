"""The roller sheet is edited, not appended to.

The shared repository fills a visit's empty seeded row, which is right for a
round captured once. A thickness corrected on the sheet must replace the one
already there, or the roller would carry two values for the same point.
"""

from __future__ import annotations

from modules.measurements.infrastructure.models import Reading
from modules.measurements.infrastructure.repositories import DjangoReadingRepository


class ReplacingReadingRepository(DjangoReadingRepository):
    def add(self, *, company_id, service_visit_id, item, **kwargs) -> int:
        Reading.objects.filter(
            company_id=company_id, service_visit_id=service_visit_id, point_id=item.point_id,
            magnitude__code=item.magnitude_code, aggregation=item.aggregation,
        ).update(value=None, condition_status=None, threshold_set_id=None)
        return super().add(
            company_id=company_id, service_visit_id=service_visit_id, item=item, **kwargs
        )
