"""UT on the press rollers' journals, and what the report says per group (Q15).

- `ut-rollers/orders/<id>/journals/?group=` — the detail table of each side:
  per roller its diameter, external and total length, access and state, and
  the findings on that side.
- `ut-rollers/orders/<id>/results/` — the "Resumen de resultados", built
  from the findings, group by group and side by side.
- `ut-rollers/orders/<id>/groups/<group>/report/` — conclusions,
  recommendations, the group's plan and its photographic record.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.core.infrastructure.audit import record
from modules.core.infrastructure.transactions import tenant_atomic
from modules.media.infrastructure.refs import image_ref
from modules.ut_rollers.domain.rollers import SIDES
from modules.ut_rollers.infrastructure.journals import MEASURES, journal_sides, results_of
from modules.ut_rollers.interfaces.common import find_order, lock_of, require, rollers_of, visit_for
from modules.ut_rollers.models import JournalInspection, RollerGroupReport

ACCESS = dict(JournalInspection.ACCESS)


class JournalSheetView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, order_id: int):
        require(request, "ut_rollers.view")
        order = find_order(request, order_id)
        group_id = int(request.query_params.get("group") or 0)
        if not group_id:
            raise ValidationError("Falta el parámetro 'group'")
        return Response(_journals(request, order, group_id))

    @tenant_atomic
    def post(self, request, order_id: int):
        """`{"group", "side", "rows": [{equipment, diameter_mm, …, access,
        access_note, state_text}]}` — one side of one group at a time."""
        actor = require(request, "ut_rollers.capture")
        order = find_order(request, order_id)
        group_id = int(request.data.get("group") or 0)
        side = request.data.get("side")
        if side not in SIDES:
            raise ValidationError("Indica el lado: mando o transmisión")
        rollers = {row.id: row for row in rollers_of(request, group_id)}
        saved = 0
        for item in request.data.get("rows") or []:
            roller = rollers.get(int(item.get("equipment") or 0))
            if roller is None:
                raise ValidationError("Un rodillo no pertenece a ese conjunto")
            access = item.get("access") or "ok"
            if access not in ACCESS:
                raise ValidationError("Acceso desconocido")
            visit_for(request, actor, order, roller)  # ownership and lock, like the thickness sheet
            JournalInspection.objects.update_or_create(
                company_id=request.company_id,
                service_order=order,
                equipment=roller,
                side=side,
                defaults={
                    **{field: _decimal(item.get(field)) for field in MEASURES},
                    "access": access,
                    "access_note": (item.get("access_note") or "").strip()[:200],
                    "state_text": (item.get("state_text") or "").strip(),
                    "created_by": request.user,
                },
            )
            saved += 1
        record(
            request,
            "ut_rollers.journals_saved",
            object_type="service_order",
            object_id=order.id,
            after={"group": group_id, "side": side, "rollers": saved},
        )
        return Response(_journals(request, order, group_id), status=201)


class ResultsSummaryView(APIView):
    """`GET ut-rollers/orders/<id>/results/` — every group of rollers the
    order touched, and each side's findings."""

    permission_classes = (IsAuthenticated,)

    def get(self, request, order_id: int):
        require(request, "ut_rollers.view")
        order = find_order(request, order_id)
        return Response({"rows": results_of(request.company_id, order)})


class GroupReportView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, order_id: int, group_id: int):
        require(request, "ut_rollers.view")
        order = find_order(request, order_id)
        report = (
            RollerGroupReport.objects.for_company(request.company_id)
            .filter(service_order=order, asset_group_id=group_id)
            .first()
        )
        return Response(_report_payload(report, order, group_id, lock_of(request, order, group_id)))

    @tenant_atomic
    def patch(self, request, order_id: int, group_id: int):
        require(request, "ut_rollers.capture")
        report = _report(request, find_order(request, order_id), group_id)
        for field in ("conclusions", "recommendations"):
            if field in request.data:
                setattr(report, field, (request.data.get(field) or "").strip())
        report.save()
        return Response(
            _report_payload(
                report, report.service_order, group_id, lock_of(request, report.service_order, group_id)
            )
        )


class GroupReportImageView(APIView):
    """`POST …/report/images/` with `role` (plan, photo), `file` and an
    optional `caption`; the plan replaces the one before, photos add up.
    `DELETE …/report/images/<asset_id>/`."""

    permission_classes = (IsAuthenticated,)
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, order_id: int, group_id: int):
        require(request, "ut_rollers.capture")
        report = _report(request, find_order(request, order_id), group_id)
        role = request.data.get("role")
        if role not in ("plan", "photo"):
            raise ValidationError("La imagen es el plano del conjunto o una foto del registro")
        from modules.media.infrastructure.uploads import UploadRejectedError, store_upload

        try:
            asset, _ = store_upload(
                company_id=request.company_id,
                upload=request.FILES.get("file"),
                kind="blueprint" if role == "plan" else "photo",
                owner_type="ut_group_report",
                owner_id=report.id,
                caption=(request.data.get("caption") or "").strip(),
                user=request.user,
            )
        except UploadRejectedError as cause:
            raise ValidationError(str(cause)) from cause
        if role == "plan":
            report.plan_image = asset
            report.save(update_fields=["plan_image"])
        return Response(
            _report_payload(
                report, report.service_order, group_id, lock_of(request, report.service_order, group_id)
            ),
            status=201,
        )

    def delete(self, request, order_id: int, group_id: int, asset_id: int):
        require(request, "ut_rollers.capture")
        report = _report(request, find_order(request, order_id), group_id)
        from modules.media.infrastructure.models import MediaAsset

        if report.plan_image_id == asset_id:
            report.plan_image = None
            report.save(update_fields=["plan_image"])
        MediaAsset.objects.for_company(request.company_id).filter(
            owner_type="ut_group_report", owner_id=report.id, id=asset_id
        ).delete()
        return Response(
            _report_payload(
                report, report.service_order, group_id, lock_of(request, report.service_order, group_id)
            )
        )


# ---------------------------------------------------------------- helpers


def _journals(request, order, group_id: int) -> dict:
    return {
        "order": {"id": order.id, "code": order.code},
        "group_id": group_id,
        "sides": journal_sides(request.company_id, order, rollers_of(request, group_id)),
        "lock_reason": lock_of(request, order, group_id),
    }


def _decimal(raw) -> Decimal | None:
    if raw in (None, ""):
        return None
    try:
        value = Decimal(str(raw).replace(",", "."))
    except InvalidOperation as cause:
        raise ValidationError(f"'{raw}' no es un número") from cause
    if value < 0:
        raise ValidationError("Una medida no puede ser negativa")
    return value


def _report(request, order, group_id: int) -> RollerGroupReport:
    from modules.assets.models import AssetGroup

    if not AssetGroup.objects.for_company(request.company_id).filter(id=group_id).exists():
        raise ValidationError("Ese conjunto no existe")
    report, _ = RollerGroupReport.objects.get_or_create(
        company_id=request.company_id,
        service_order=order,
        asset_group_id=group_id,
        defaults={"created_by": request.user},
    )
    return report


def _report_payload(report: RollerGroupReport | None, order, group_id: int, lock: str | None = None) -> dict:
    from modules.media.infrastructure.models import MediaAsset

    if report is None:
        return {
            "id": None,
            "order_id": order.id,
            "group_id": group_id,
            "conclusions": "",
            "recommendations": "",
            "plan": None,
            "photos": [],
            "lock_reason": lock,
        }
    photos = (
        MediaAsset.objects.for_company(report.company_id)
        .filter(owner_type="ut_group_report", owner_id=report.id, kind="photo")
        .order_by("created_at", "id")
    )
    return {
        "id": report.id,
        "order_id": order.id,
        "group_id": group_id,
        "conclusions": report.conclusions,
        "recommendations": report.recommendations,
        "plan": image_ref(report.plan_image) if report.plan_image_id else None,
        "photos": [image_ref(asset) for asset in photos],
        "lock_reason": lock,
    }
