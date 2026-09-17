from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.measurements.models import Reading


class TrendView(APIView):
    """The point × date matrix of `TABLA DE TENDENCIAS.xls`, straight from the
    time series."""

    permission_classes = [IsAuthenticated]

    def get(self, request, equipment_id: int):
        language = getattr(request, "language", "es")
        queryset = (
            Reading.objects.for_company(request.company_id)
            .filter(point__equipment_id=equipment_id)
            .select_related("point", "magnitude", "unit", "condition_status")
            .order_by("point__number", "point__axis", "taken_at")
        )
        if request.query_params.get("magnitude"):
            queryset = queryset.filter(magnitude__code=request.query_params["magnitude"])

        series: dict[tuple[str, str], dict] = {}
        for reading in queryset:
            key = (reading.point.label, reading.magnitude.code)
            entry = series.setdefault(key, {
                "point_label": reading.point.label,
                "magnitude_code": reading.magnitude.code,
                "magnitude_name": reading.magnitude.translated("name", language),
                "unit": reading.unit.code,
                "readings": [],
            })
            entry["readings"].append({
                "taken_at": reading.taken_at.date().isoformat(),
                "value": float(reading.value) if reading.value is not None else None,
                "status_code": reading.condition_status.code if reading.condition_status else None,
                "not_measured_reason": reading.not_measured_reason or None,
            })
        return Response(list(series.values()))
