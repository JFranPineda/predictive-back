"""The day's rules, applied to other modules' writes (F3-03, Q17, Q19).

Runs in `WriteGuardMiddleware`, before DRF has authenticated anyone, so it
reads the bearer token itself. An invalid token is left for DRF to reject:
the guard only ever refuses, it never lets through what DRF would not.

Two refusals:

- 423 once the day of the data is closed;
- 428 while no service of that train has started that day — its ATS and the
  three start signatures, or an administrator's unlock (Q19).
"""

from __future__ import annotations

import json
from datetime import date

from django.http import JsonResponse
from django.utils import timezone

from modules.core.infrastructure.module_gate import module_of
from modules.workday.domain.rules import MANAGE, UNLOCKED_MODULES, day_closed
from modules.workday.infrastructure.jobs import allows

# What a photo or a document may belong to and still be a picture of a train.
# A service's own signatures are the workday module's, and never guarded.
MEDIA_OWNERS = frozenset({"visit", "point", "equipment"})


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
    day, plant_id, group_id, order_id = subject
    if day is not None and day != today and _closed(company_id, day, plant_id):
        return _locked(day)
    if group_id is not None and not allows(company_id, group_id, day or today, order_id):
        return JsonResponse(
            {
                "detail": "El servicio de este conjunto no ha comenzado: faltan su ATS y las firmas "
                "de inicio del ingeniero de producción, el líder del servicio y el supervisor "
                "de planta, o que un administrador lo desbloquee.",
                "type": "service_not_started",
                "status": 428,
            },
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


def _subject(request, module, view_func, view_kwargs):
    """(day, plant, train, order) of what the write touches, or None when it
    is not a train's data (catalogues, users, orders themselves)."""
    view_name = getattr(getattr(view_func, "view_class", None), "__name__", "")
    body = _body(request)
    if module == "media" and view_name == "MediaCollectionView":
        owner_type = request.POST.get("owner_type") or "visit"
        owner_id = request.POST.get("owner_id")
        if owner_type not in MEDIA_OWNERS or not owner_id:
            return None
        return _of_owner(owner_type, int(owner_id))
    if "visit_id" in view_kwargs:
        return _of_visit(view_kwargs["visit_id"])
    if module == "maintenance" and "record_id" in view_kwargs:
        from modules.maintenance.models import WorkRecord

        row = (
            WorkRecord.objects.filter(id=view_kwargs["record_id"])
            .values("shift_date", "asset_group__sector__area__plant_id", "asset_group_id")
            .first()
        )
        if row:
            return row["shift_date"], row["asset_group__sector__area__plant_id"], row["asset_group_id"], None
        return None
    if module == "alignment":
        return _of_alignment(view_name, view_kwargs, body)
    if module == "topography":
        return _of_topography(view_kwargs, body)
    if module == "ut_rollers":
        return _of_rollers(view_name, view_kwargs, body)
    return None


def _of_owner(owner_type: str, owner_id: int):
    if owner_type == "visit":
        return _of_visit(owner_id)
    from modules.assets.models import MeasurementPoint

    if owner_type == "point":
        equipment_id = (
            MeasurementPoint.objects.filter(id=owner_id).values_list("equipment_id", flat=True).first()
        )
    else:
        equipment_id = owner_id
    return _of_equipment(equipment_id)


def _of_equipment(equipment_id):
    from modules.assets.models import Equipment

    row = (
        Equipment.objects.filter(id=equipment_id)
        .values("asset_group_id", "asset_group__sector__area__plant_id")
        .first()
    )
    if row is None:
        return None
    return None, row["asset_group__sector__area__plant_id"], row["asset_group_id"], None


def _of_group(group_id):
    from modules.assets.models import AssetGroup

    plant_id = AssetGroup.objects.filter(id=group_id).values_list("sector__area__plant_id", flat=True).first()
    if plant_id is None:
        return None
    return None, plant_id, int(group_id), None


def _of_visit(visit_id):
    from modules.services.models import ServiceVisit

    row = (
        ServiceVisit.objects.filter(id=visit_id)
        .values("visited_at", "service_order__plant_id", "service_order_id", "equipment__asset_group_id")
        .first()
    )
    if row is None:
        return None
    return (
        timezone.localtime(row["visited_at"]).date(),
        row["service_order__plant_id"],
        row["equipment__asset_group_id"],
        row["service_order_id"],
    )


def _of_alignment(view_name, view_kwargs, body):
    if "record_id" in view_kwargs:
        from modules.alignment.models import AlignmentRecord

        row = (
            AlignmentRecord.objects.filter(id=view_kwargs["record_id"])
            .values("asset_group_id", "service_visit_id")
            .first()
        )
        if row is None:
            return None
        return (
            _of_visit(row["service_visit_id"])
            if row["service_visit_id"]
            else _of_group(row["asset_group_id"])
        )
    if view_name == "AlignmentRecordListView":
        if body.get("service_visit"):
            return _of_visit(body["service_visit"])
        return _of_group(body.get("asset_group")) if body.get("asset_group") else None
    return None


def _of_topography(view_kwargs, body):
    visit_id = body.get("service_visit")
    for key, model in (("reading_id", "TopographyElementReading"), ("survey_id", "TopographySurvey")):
        if key in view_kwargs:
            from modules.topography import models

            visit_id = (
                getattr(models, model)
                .objects.filter(id=view_kwargs[key])
                .values_list("service_visit_id", flat=True)
                .first()
            )
    return _of_visit(visit_id) if visit_id else None


def _of_rollers(view_name, view_kwargs, body):
    if "indication_id" in view_kwargs:
        from modules.ut_rollers.models import UTIndication

        equipment_id = (
            UTIndication.objects.filter(id=view_kwargs["indication_id"])
            .values_list("equipment_id", flat=True)
            .first()
        )
        return _of_equipment(equipment_id)
    if view_name == "IndicationListView" and body.get("equipment"):
        return _of_equipment(body["equipment"])
    if "order_id" in view_kwargs and body.get("group"):
        subject = _of_group(body["group"])
        return subject and (subject[0], subject[1], subject[2], int(view_kwargs["order_id"]))
    return None


def _body(request) -> dict:
    if request.content_type != "application/json":
        return request.POST
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _locked(day: date) -> JsonResponse:
    return JsonResponse(
        {
            "detail": f"La jornada del {day:%d/%m/%Y} está cerrada: ya no se pueden modificar sus datos.",
            "type": "workday_closed",
            "status": 423,
        },
        status=423,
    )
