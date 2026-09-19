"""Field capture: one equipment's whole round in one transaction.

Everything that must happen afterwards (equipment status, KPIs, notifications)
is an event subscription, not a line in this use case.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from modules.core.domain.events import ReadingRecorded
from modules.core.domain.ports import EventPublisher
from modules.thresholds.domain.entities import Aggregation, EvaluationContext
from modules.thresholds.domain.services import classify_context, evaluate, resolve


@dataclass(frozen=True, slots=True)
class ReadingInput:
    point_id: int
    magnitude_code: str
    value: Decimal | None
    unit_code: str
    aggregation: str = "rms"
    quality: str = "ok"
    not_measured_reason: str = ""
    notes: str = ""


@dataclass(frozen=True, slots=True)
class RecordedReading:
    reading_id: int
    point_id: int
    magnitude_code: str
    condition_status: str | None
    threshold_set_id: int | None


class RecordReadings:
    def __init__(self, readings_repo, thresholds_repo, points_repo, events: EventPublisher) -> None:
        self._readings = readings_repo
        self._thresholds = thresholds_repo
        self._points = points_repo
        self._events = events

    def execute(
        self,
        *,
        company_id: int,
        service_visit_id: int,
        taken_at: datetime,
        inputs: tuple[ReadingInput, ...],
        operator_id: int,
        idempotency_key: str | None = None,
    ) -> tuple[RecordedReading, ...]:
        if idempotency_key and self._readings.batch_exists(idempotency_key):
            return self._readings.batch_results(idempotency_key)

        contexts = self._points.contexts_for(tuple(i.point_id for i in inputs))
        recorded: list[RecordedReading] = []

        for item in inputs:
            evaluation = self._evaluate(company_id, item, contexts[item.point_id], taken_at)
            reading_id = self._readings.add(
                company_id=company_id,
                service_visit_id=service_visit_id,
                taken_at=taken_at,
                item=item,
                operator_id=operator_id,
                condition_status=evaluation.status.code if evaluation.status else None,
                threshold_set_id=evaluation.threshold_set_id,
            )
            recorded.append(
                RecordedReading(
                    reading_id=reading_id,
                    point_id=item.point_id,
                    magnitude_code=item.magnitude_code,
                    condition_status=evaluation.status.code if evaluation.status else None,
                    threshold_set_id=evaluation.threshold_set_id,
                )
            )
            if item.value is not None:
                self._events.publish(
                    ReadingRecorded(
                        occurred_at=datetime.now(UTC),
                        company_id=company_id,
                        reading_id=reading_id,
                        point_id=item.point_id,
                        magnitude_code=item.magnitude_code,
                        value=item.value,
                        condition_status=evaluation.status.code if evaluation.status else None,
                    )
                )

        if idempotency_key:
            self._readings.record_batch(idempotency_key, service_visit_id, len(recorded))
        return tuple(recorded)

    def _evaluate(self, company_id: int, item: ReadingInput, point_context, taken_at: datetime):
        if item.value is None:
            from modules.thresholds.domain.entities import Evaluation

            return Evaluation(status=None, threshold_set_id=None, unmatched=True)
        candidates = self._thresholds.candidates(company_id, item.magnitude_code)
        context = EvaluationContext(
            magnitude_code=item.magnitude_code,
            aggregation=Aggregation(item.aggregation),
            point_id=point_context.point_id,
            equipment_id=point_context.equipment_id,
            equipment_type=point_context.equipment_type,
            asset_group_kind=point_context.asset_group_kind,
            machine_class=point_context.machine_class,
            # Without the standard every set is out of play and the reading
            # comes back ungraded; without the plate the class cannot be
            # derived for the machines nobody classified by hand.
            standard_code=getattr(point_context, "standard_code", None),
            rated_power_kw=getattr(point_context, "rated_power_kw", None),
            mounting=getattr(point_context, "mounting", None),
        )
        chosen = resolve(candidates, classify_context(context, None), taken_at.date())
        return evaluate(item.value, chosen)
