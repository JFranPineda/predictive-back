"""The day's rules, applied to other modules' writes (F3-03, F3-04).

Runs in `WriteGuardMiddleware`, before DRF has authenticated anyone, so it
reads the bearer token itself. An invalid token is left for DRF to reject:
the guard only ever refuses, it never lets through what DRF would not.
"""

from __future__ import annotations

import json
from datetime import date

from django.http import JsonResponse
from django.utils import timezone

from modules.core.infrastructure.module_gate import module_of
from modules.workday.domain.rules import MANAGE, UNLOCKED_MODULES, PermitRef, day_closed, permit_valid

# Where a photo or an observation names its train. Anything else — an ATS's
# own signed copy, a roller indication — is not a picture of the train.
PHOTO_OWNERS = frozenset({"visit", "point", "equipment"})


def guard(request, view_func, view_kwargs):
    module = module_of(view_func)
    if module is None or module in UNLOCKED_MODULES:
        return None
    user, company_id = _identify(request)
    if user is None or company_id is None:
        return None

    from modules.security.application.access import permissions_for

    if MANAGE in permissions_for(user, company_id):
        return None

    today = timezone.localdate()
    if _closed(company_id, today):
        return _locked(today)

    subject = _subject(request, module, view_func, view_kwargs)
    if subject is None:
        return None
    visit_date, plant_id, group_id, needs_permit = subject
    if visit_date is not None and visit_date != today and _closed(company_id, visit_date, plant_id):
        return _locked(visit_date)
    if needs_permit and group_id is not None and not _has_permit(company_id, group_id, today):
        return JsonResponse(
            {"detail": "Sin ATS vigente para este conjunto en la jornada de hoy: regístralo "
                       "y sube el ATS firmado antes de fotografiar u observar el conjunto.",
             "type": "permit_required", "status": 428},
            status=428,
        )
    return None


def _identify(request):
    from rest_framework_simplejwt.authentication import JWTAuthentication
    from rest_framework_simplejwt.exceptions import AuthenticationFailed, InvalidToken

    from modules.security.application.access import resolve_company

    auth = JWTAuthentication()
    header = auth.get_header(request)
    try:
        # A malformed header raises here too: DRF answers it with a 401.
        raw = auth.get_raw_token(header) if header else None
        if raw is None:
            return None, None
        user = auth.get_user(auth.get_validated_token(raw))
        return user, resolve_company(user, request.headers.get("X-Company-Id"))
    except (InvalidToken, AuthenticationFailed, PermissionError, ValueError):
        return None, None


def _closed(company_id: int, day: date, plant_id: int | None = None) -> bool:
    from modules.workday.models import Workday

    rows = Workday.objects.for_company(company_id).filter(date=day)
    if plant_id is not None:
        rows = rows.filter(plant_id=plant_id)
    return day_closed(closed is None for closed in rows.values_list("closed_at", flat=True))


def _has_permit(company_id: int, group_id: int, today: date) -> bool:
    from modules.assets.models import AssetGroup
    from modules.workday.models import SafetyPermit, Workday

    plant_id = (
        AssetGroup.objects.filter(id=group_id).values_list("sector__area__plant_id", flat=True).first()
    )
    workday = Workday.objects.for_company(company_id).filter(plant_id=plant_id, date=today).first()
    if workday is None:
        return False
    permits = [
        PermitRef(asset_group_id=row["asset_group_id"], has_document=row["document_id"] is not None)
        for row in SafetyPermit.objects.filter(workday=workday).values("asset_group_id", "document_id")
    ]
    return permit_valid(permits, group_id, workday_open=workday.is_open)


def _subject(request, module, view_func, view_kwargs):
    """(visit date, plant, train, whether it is a photo or an observation)."""
    view_name = getattr(getattr(view_func, "view_class", None), "__name__", "")
    if module == "media" and view_name == "MediaCollectionView":
        owner_type = request.POST.get("owner_type") or "visit"
        owner_id = request.POST.get("owner_id")
        if owner_type not in PHOTO_OWNERS or not owner_id:
            return None
        return _of_owner(owner_type, int(owner_id))
    if "visit_id" in view_kwargs and module == "services":
        visit_date, plant_id, group_id = _of_visit(view_kwargs["visit_id"])
        observing = view_name == "VisitEntriesView" and _body(request).get("entry_type") == "observation"
        return visit_date, plant_id, group_id, observing
    if "record_id" in view_kwargs and module == "maintenance":
        from modules.maintenance.models import WorkRecord

        row = WorkRecord.objects.filter(id=view_kwargs["record_id"]).values(
            "shift_date", "asset_group__sector__area__plant_id", "asset_group_id"
        ).first()
        if row:
            plant_id = row["asset_group__sector__area__plant_id"]
            return row["shift_date"], plant_id, row["asset_group_id"], False
    return None


def _of_owner(owner_type: str, owner_id: int):
    if owner_type == "visit":
        visit_date, plant_id, group_id = _of_visit(owner_id)
        return visit_date, plant_id, group_id, True
    from modules.assets.models import Equipment, MeasurementPoint

    if owner_type == "point":
        points = MeasurementPoint.objects.filter(id=owner_id)
        equipment_id = points.values_list("equipment_id", flat=True).first()
    else:
        equipment_id = owner_id
    row = Equipment.objects.filter(id=equipment_id).values(
        "asset_group_id", "asset_group__sector__area__plant_id"
    ).first()
    if row is None:
        return None
    return None, row["asset_group__sector__area__plant_id"], row["asset_group_id"], True


def _of_visit(visit_id):
    from modules.services.models import ServiceVisit

    row = ServiceVisit.objects.filter(id=visit_id).values(
        "visited_at", "service_order__plant_id", "equipment__asset_group_id"
    ).first()
    if row is None:
        return None, None, None
    return (
        timezone.localtime(row["visited_at"]).date(),
        row["service_order__plant_id"],
        row["equipment__asset_group_id"],
    )


def _body(request) -> dict:
    if request.content_type != "application/json":
        return request.POST
    try:
        return json.loads(request.body or b"{}")
    except ValueError:
        return {}


def _locked(day: date) -> JsonResponse:
    return JsonResponse(
        {"detail": f"La jornada del {day:%d/%m/%Y} está cerrada: ya no se pueden modificar sus datos.",
         "type": "workday_closed", "status": 423},
        status=423,
    )
