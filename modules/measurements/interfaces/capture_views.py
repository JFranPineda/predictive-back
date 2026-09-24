"""Field capture: one machine's whole round, in one request.

This is the path `RecordReadings` was written for and never got: creating the
readings of a visit in bulk, grading each one through the cascade as it lands,
and surviving the retry a crew makes when the upload drops halfway.

It is not the same thing as the record of values, which edits readings that
already exist. A round that has never been captured has nothing to edit.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.core.infrastructure.bus import bus
from modules.measurements.application.record_readings import ReadingInput, RecordReadings
from modules.measurements.infrastructure.repositories import (
    DjangoPointContextRepository,
    DjangoReadingRepository,
)
from modules.security.application.access import build_actor
from modules.security.domain.policies import VisitRef, can_record_reading
from modules.services.models import ServiceVisit
from modules.thresholds.infrastructure.repositories import DjangoThresholdRepository

MAX_READINGS = 500


class VisitCaptureView(APIView):
    """`POST service-visits/<id>/readings/bulk/`.

    The `Idempotency-Key` header is what makes a retry safe: the same key
    returns the first answer instead of doubling the round.
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, visit_id: int):
        visit = (
            ServiceVisit.objects.for_company(request.company_id)
            .select_related("equipment__asset_group__sector__area")
            .prefetch_related("participants")
            .filter(id=visit_id)
            .first()
        )
        if visit is None:
            return Response({"type": "not_found", "status": 404}, status=404)

        actor = build_actor(request.user, request.company_id)
        if not can_record_reading(actor, _reference(visit)):
            raise PermissionDenied("No puedes registrar lecturas en esta visita")

        rows = request.data.get("readings") or []
        if not rows:
            raise ValidationError("No llegó ninguna lectura")
        if len(rows) > MAX_READINGS:
            raise ValidationError(f"Como máximo {MAX_READINGS} lecturas por envío")

        inputs = tuple(_to_input(row) for row in rows)
        use_case = RecordReadings(
            readings_repo=DjangoReadingRepository(),
            thresholds_repo=DjangoThresholdRepository(getattr(request, "language", "es")),
            points_repo=DjangoPointContextRepository(),
            events=bus,
        )
        recorded = use_case.execute(
            company_id=request.company_id,
            service_visit_id=visit.id,
            taken_at=visit.visited_at or datetime.now(UTC),
            inputs=inputs,
            operator_id=request.user.id,
            idempotency_key=request.headers.get("Idempotency-Key") or None,
        )
        from modules.core.infrastructure.audit import record

        record(
            request, "reading.captured", object_type="visit", object_id=visit.id,
            after={
                "readings": len(recorded),
                "worst": _worst(recorded),
                "equipment": visit.equipment.client_tag or visit.equipment.asset_code,
            },
        )
        return Response({
            "recorded": len(recorded),
            "readings": [
                {
                    "reading_id": row.reading_id,
                    "point_id": row.point_id,
                    "magnitude_code": row.magnitude_code,
                    "condition_status": row.condition_status,
                }
                for row in recorded
            ],
        }, status=201)


def _to_input(row: dict) -> ReadingInput:
    point = row.get("point_id")
    magnitude = (row.get("magnitude_code") or "").strip()
    if not point or not magnitude:
        raise ValidationError("Cada lectura necesita punto y magnitud")
    return ReadingInput(
        point_id=int(point),
        magnitude_code=magnitude,
        value=_decimal(row.get("value")),
        unit_code=(row.get("unit_code") or "").strip(),
        aggregation=row.get("aggregation") or "rms",
        quality=row.get("quality") or "ok",
        not_measured_reason=row.get("not_measured_reason") or "",
        notes=(row.get("notes") or "").strip(),
    )


def _decimal(value) -> Decimal | None:
    """A blank is "not measured", which is a row the plan coverage KPI counts."""

    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation as cause:
        raise ValidationError(f"Valor no numérico: {value}") from cause


def _reference(visit: ServiceVisit) -> VisitRef:
    participants = list(visit.participants.all())
    return VisitRef(
        id=visit.id,
        area_id=visit.equipment.asset_group.sector.area_id,
        participant_ids=frozenset(row.user_id for row in participants),
        lead_analyst_id=next(
            (row.user_id for row in participants if row.role == "lead_analyst"), None
        ),
        is_closed=visit.is_closed,
        report_issued=False,
        visited_on=visit.visited_at.date() if visit.visited_at else None,
    )


def _worst(recorded) -> str | None:
    """The verdict the round produced, for the audit line a manager scans."""
    rank = {"operational": 1, "alarm": 2, "shutdown": 3}
    codes = [row.condition_status for row in recorded if row.condition_status]
    return max(codes, key=lambda code: rank.get(code, 0)) if codes else None
