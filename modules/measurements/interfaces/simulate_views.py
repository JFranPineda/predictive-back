"""`POST /threshold-sets/{id}/simulate/` — what a criterion would change.

The thresholds screen offered "Simular impacto" against a route nobody had
built, so the answer was always an error. It lives here because the readings
are measurements': thresholds knows the criteria, not what was measured.

A dry run of the regrade: the latest reading of each point for the set's
magnitude is graded again with the cascade as it stands. A point counts when
this set is the one that decides it and its verdict would differ from the one
stored. Nothing is written.
"""

from __future__ import annotations

from datetime import date

from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.assets.infrastructure.visibility import visible_equipments
from modules.assets.models import Equipment
from modules.measurements.models import Reading
from modules.security.infrastructure.access import build_actor
from modules.thresholds.domain.services import evaluate, resolve, tally_impact
from modules.thresholds.infrastructure.evaluation import context_for
from modules.thresholds.infrastructure.models import ThresholdSet
from modules.thresholds.infrastructure.repositories import DjangoThresholdRepository


class ThresholdSetSimulateView(APIView):
    def post(self, request, set_id: int):
        if not build_actor(request.user, request.company_id).has("thresholds.manage_set"):
            raise PermissionDenied("Falta el permiso thresholds.manage_set")
        threshold_set = ThresholdSet.objects.for_company(request.company_id).filter(id=set_id).first()
        if threshold_set is None:
            raise NotFound("El juego de umbrales no existe")

        code, aggregation = threshold_set.magnitude_code, threshold_set.aggregation
        # Only what this person may see: an area-bound manager is not told
        # about the machines of other areas.
        equipments = visible_equipments(request, Equipment.objects.for_company(request.company_id))
        # The latest reading of each point, in two cheap steps: a correlated
        # "latest per point" subquery took forty seconds on 60,000 readings.
        latest: dict[int, int] = {}
        for reading_id, point_id in (
            Reading.objects.for_company(request.company_id)
            .filter(magnitude__code=code, aggregation=aggregation, value__isnull=False,
                    point__equipment__in=equipments)
            .order_by("point_id", "-taken_at")
            .values_list("id", "point_id")
        ):
            latest.setdefault(point_id, reading_id)
        readings = Reading.objects.filter(id__in=latest.values()).select_related(
            "condition_status", "point__equipment__asset_group__kind",
            "point__equipment__applied_standard", "point__equipment__machine_class",
            "point__equipment__nameplate", "service_visit__service_order__standard",
        )

        candidates = DjangoThresholdRepository().candidates(request.company_id, code)
        # A criterion that starts later is simulated from the day it starts.
        moment = max(date.today(), threshold_set.valid_from)
        verdicts = []
        for reading in readings:
            order = reading.service_visit.service_order if reading.service_visit_id else None
            context = context_for(reading.point.equipment, code, aggregation, reading.point_id,
                                  standard=order.standard if order else None)
            winner = resolve(candidates, context, moment)
            if winner is None or winner.id != threshold_set.id:
                continue
            verdict = evaluate(reading.value, winner)
            before = reading.condition_status.code if reading.condition_status_id else None
            verdicts.append((reading.point.equipment_id, before, verdict.status))

        changed, by_status = tally_impact(verdicts)
        return Response({"judged": len(verdicts), "changed": changed, "by_status": by_status})
