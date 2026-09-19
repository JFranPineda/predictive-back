"""The adapters `RecordReadings` was written against.

The use case shipped complete — grading, events, idempotency — and nothing
implemented its ports, so field capture had no way in. These are the three
small translations it needs: one to write a reading, one to describe the point
it belongs to, and one to remember a batch that already arrived.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from modules.measurements.application.record_readings import (
    ReadingInput,
    RecordedReading,
)
from modules.measurements.infrastructure import models


@dataclass(frozen=True, slots=True)
class PointContext:
    point_id: int
    equipment_id: int
    equipment_type: str
    asset_group_kind: str | None
    machine_class: str | None
    # The cascade drops every set from another standard, and derives the class
    # from the nameplate when nobody set one. Leaving these out is why a
    # perfectly ordinary 4.8 mm/s came back ungraded.
    standard_code: str | None = None
    rated_power_kw: float | None = None
    mounting: str | None = None


class DjangoPointContextRepository:
    """What the cascade needs to know about a point, in one query.

    The machine class is read from the equipment rather than guessed, because
    a set that names a class only competes for machines of that class.
    """

    def contexts_for(self, point_ids: tuple[int, ...]) -> dict[int, PointContext]:
        from modules.assets.models import MeasurementPoint

        rows = (
            MeasurementPoint.objects.filter(id__in=point_ids)
            .select_related(
                "equipment__asset_group__kind",
                "equipment__machine_class",
                "equipment__applied_standard",
                "equipment__nameplate",
            )
        )
        return {
            row.id: PointContext(
                point_id=row.id,
                equipment_id=row.equipment_id,
                equipment_type=row.equipment.equipment_type,
                asset_group_kind=(
                    row.equipment.asset_group.kind.code
                    if row.equipment.asset_group.kind_id
                    else None
                ),
                machine_class=(
                    row.equipment.machine_class.code
                    if row.equipment.machine_class_id
                    else None
                ),
                standard_code=(
                    row.equipment.applied_standard.code
                    if row.equipment.applied_standard_id
                    else None
                ),
                rated_power_kw=_plate(row.equipment, "rated_power_kw"),
                mounting=_plate(row.equipment, "mounting"),
            )
            for row in rows
        }


class DjangoReadingRepository:
    """Writes the reading and remembers the batch it came in.

    `ReadingBatch` exists for one reason: a crew loses signal halfway through
    uploading an equipment and retries the whole thing. Replaying the same key
    has to return the first answer, not a second set of readings.
    """

    def __init__(self, operator_id: int | None = None) -> None:
        self._operator_id = operator_id
        # What this request wrote, so the batch can record exactly that.
        self._written: list[int] = []

    def add(
        self,
        *,
        company_id: int,
        service_visit_id: int,
        taken_at: datetime,
        item: ReadingInput,
        operator_id: int,
        condition_status: str | None,
        threshold_set_id: int | None,
    ) -> int:
        magnitude = models.Magnitude.objects.select_related("default_unit").get(
            code=item.magnitude_code
        )
        unit = (
            models.Unit.objects.filter(code=item.unit_code).first()
            or magnitude.default_unit
        )
        status = None
        if condition_status:
            from modules.thresholds.models import Status

            status = (
                Status.objects.for_company(company_id)
                .filter(code=condition_status, kind="condition")
                .first()
            )
        reading = models.Reading.objects.create(
            company_id=company_id,
            service_visit_id=service_visit_id,
            taken_at=taken_at,
            point_id=item.point_id,
            magnitude=magnitude,
            value=item.value,
            unit=unit,
            aggregation=item.aggregation,
            condition_status=status,
            threshold_set_id=threshold_set_id,
            operator_id=operator_id,
            quality=item.quality,
            not_measured_reason=item.not_measured_reason,
            notes=item.notes,
        )
        self._written.append(reading.id)
        return reading.id

    def batch_exists(self, idempotency_key: str) -> bool:
        return models.ReadingBatch.objects.filter(idempotency_key=idempotency_key).exists()

    def batch_results(self, idempotency_key: str) -> tuple[RecordedReading, ...]:
        """The readings the first attempt produced, not a fresh set."""

        batch = models.ReadingBatch.objects.filter(idempotency_key=idempotency_key).first()
        if batch is None:
            return ()
        rows = (
            models.Reading.objects.filter(id__in=batch.reading_ids or [])
            .select_related("magnitude", "condition_status")
            .order_by("id")
        )
        return tuple(
            RecordedReading(
                reading_id=row.id,
                point_id=row.point_id,
                magnitude_code=row.magnitude.code,
                condition_status=row.condition_status.code if row.condition_status else None,
                threshold_set_id=row.threshold_set_id,
            )
            for row in rows
        )

    def record_batch(self, idempotency_key: str, service_visit_id: int, count: int) -> None:
        models.ReadingBatch.objects.get_or_create(
            idempotency_key=idempotency_key,
            defaults={
                "service_visit_id": service_visit_id,
                "reading_count": count,
                "reading_ids": list(self._written),
            },
        )


def _plate(equipment, field: str):
    """The nameplate is optional, and a machine without one is not an error."""

    plate = getattr(equipment, "nameplate", None)
    value = getattr(plate, field, None) if plate else None
    return float(value) if field == "rated_power_kw" and value is not None else value
