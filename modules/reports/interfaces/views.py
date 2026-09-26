"""Informes MPd y END (V3-23), the monthly plant summary, and correctivos.

`?output=html` is the screen preview, `pdf` what the customer receives,
`xlsx` the workbook — all three from one context. Not `format`: DRF reserves
that name for its own renderer negotiation and answers 404 to anything else.
"""

from __future__ import annotations

from datetime import date

from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.reports.infrastructure.builders import build_corrective, build_end, build_monthly, build_mpd
from modules.reports.infrastructure.render import respond
from modules.security.application.access import build_actor

FORMATS = ("html", "pdf", "xlsx")


class _ReportView(APIView):
    permission_classes = (IsAuthenticated,)

    def format_of(self, request) -> str:
        actor = build_actor(request.user, request.company_id)
        if not actor.has("reports.view"):
            raise PermissionDenied("Falta el permiso reports.view")
        fmt = request.query_params.get("output", "html")
        if fmt not in FORMATS:
            raise ValidationError(f"Formato no soportado: {fmt}")
        return fmt


def _int(request, name: str) -> int:
    try:
        return int(request.query_params[name])
    except (KeyError, ValueError) as cause:
        raise ValidationError(f"Falta el parámetro '{name}'") from cause


def _date(request, name: str) -> date:
    try:
        return date.fromisoformat(request.query_params[name])
    except (KeyError, ValueError) as cause:
        raise ValidationError(f"'{name}' va como AAAA-MM-DD") from cause


class MpdReportView(_ReportView):
    """`GET reports/mpd/?order=&group=&output=`"""

    def get(self, request):
        fmt = self.format_of(request)
        return respond("mpd", build_mpd(request, _int(request, "order"), _int(request, "group")), fmt)


class EndReportView(_ReportView):
    """`GET reports/end/?order=&output=`"""

    def get(self, request):
        fmt = self.format_of(request)
        return respond("end", build_end(request, _int(request, "order")), fmt)


class MonthlyReportView(_ReportView):
    """`GET reports/monthly/?plant=&month=AAAA-MM&output=`"""

    def get(self, request):
        fmt = self.format_of(request)
        month = request.query_params.get("month") or date.today().strftime("%Y-%m")
        return respond("monthly", build_monthly(request, _int(request, "plant"), month), fmt)


class CorrectiveReportView(_ReportView):
    """`GET reports/corrective/?from=&to=&output=`"""

    def get(self, request):
        fmt = self.format_of(request)
        start, end = _date(request, "from"), _date(request, "to")
        if end < start:
            raise ValidationError("El fin del periodo es anterior al inicio")
        return respond("corrective", build_corrective(request, start, end), fmt)


class ReportOrdersView(_ReportView):
    """`GET reports/orders/?family=mpd|ndt` — what the pickers offer: the
    orders of one family, newest first, and the trains each one visited."""

    def get(self, request):
        self.format_of(request)
        from django.db.models import Count

        from modules.services.models import ServiceOrder, ServiceVisit

        family = request.query_params.get("family", "mpd")
        orders = list(
            ServiceOrder.objects.for_company(request.company_id)
            .filter(technique__family=family)
            .annotate(visits_count=Count("visits"))
            .filter(visits_count__gt=0)
            .select_related("technique")
            .order_by("-scheduled_from", "-id")[:300]
        )
        trains: dict[int, list] = {}
        for order_id, group_id, name in (
            ServiceVisit.objects.for_company(request.company_id)
            .filter(service_order__in=orders)
            .values_list("service_order_id", "equipment__asset_group_id", "equipment__asset_group__name")
            .distinct()
            .order_by("equipment__asset_group__name")
        ):
            trains.setdefault(order_id, []).append({"id": group_id, "name": name})
        language = getattr(request, "language", "es")
        return Response([
            {
                "id": order.id,
                "code": order.code,
                "client_work_order": order.client_work_order,
                "technique": order.technique.translated("name", language),
                "date": order.scheduled_from.isoformat(),
                "trains": trains.get(order.id, []),
            }
            for order in orders
        ])
