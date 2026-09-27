"""The workday: open, close with the chief engineer's password, and what
happens inside it — the day's works, the ATS and the field observations."""

from __future__ import annotations

from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.core.infrastructure.audit import record
from modules.core.infrastructure.transactions import tenant_atomic
from modules.security.application.access import build_actor
from modules.workday.domain.rules import (
    MANAGE,
    REOPEN,
    ObservationIncompleteError,
    check_observation,
)
from modules.workday.infrastructure.day_works import works_of
from modules.workday.infrastructure.jobs import allows
from modules.workday.models import FieldObservation, Workday


class WorkdayListView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        _require(request, "workday.view")
        rows = Workday.objects.for_company(request.company_id).select_related(
            "plant", "opened_by", "closed_by"
        )
        if request.query_params.get("plant"):
            rows = rows.filter(plant_id=request.query_params["plant"])
        if request.query_params.get("date"):
            rows = rows.filter(date=request.query_params["date"])
        return Response([_summary(row) for row in rows[:60]])

    @tenant_atomic
    def post(self, request):
        """Opens today's workday for a plant (F3-01). One per plant and day."""
        _require(request, MANAGE)
        from modules.assets.models import Plant

        plant = Plant.objects.for_company(request.company_id).filter(id=request.data.get("plant")).first()
        if plant is None:
            raise ValidationError("Elige la planta")
        today = timezone.localdate()
        if Workday.objects.filter(plant=plant, date=today).exists():
            raise ValidationError("La jornada de hoy ya está abierta en esta planta")
        row = Workday.objects.create(
            company_id=request.company_id, plant=plant, date=today, opened_at=timezone.now(),
            opened_by=request.user, notes=(request.data.get("notes") or "").strip(),
        )
        record(request, "workday.opened", object_type="workday", object_id=row.id,
               after={"plant": plant.id, "date": today.isoformat()})
        return Response(_summary(row), status=201)


class WorkdayDetailView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, workday_id: int):
        actor = _require(request, "workday.view")
        row = _workday(request, workday_id)
        from modules.workday.interfaces.job_views import job_summary

        sees_permits = any(
            actor.has(code) for code in (MANAGE, "workday.view_permits", "workday.register_permit")
        )
        return Response({
            **_summary(row),
            "works": [_work(work) for work in works_of(row)],
            "jobs": (
                [job_summary(job) for job in row.jobs.select_related(
                    "asset_group", "service_order__technique", "closed_by").prefetch_related("signatures")]
                if sees_permits else None
            ),
            "observations": [
                _observation(o) for o in row.observations.select_related("asset_group", "photo", "created_by")
            ],
        })


class WorkdayCloseView(APIView):
    """Closing takes the chief engineer's password, not only his session: the
    close is what stops everyone else, so it is signed (F3-01)."""

    permission_classes = (IsAuthenticated,)

    @tenant_atomic
    def post(self, request, workday_id: int):
        _require(request, MANAGE)
        _reauthenticate(request)
        row = _workday(request, workday_id)
        if not row.is_open:
            raise ValidationError("La jornada ya está cerrada")
        row.closed_at = timezone.now()
        row.closed_by = request.user
        if request.data.get("notes"):
            row.notes = request.data["notes"].strip()
        row.save(update_fields=["closed_at", "closed_by", "notes"])
        record(request, "workday.closed", object_type="workday", object_id=row.id,
               after={"closed_at": row.closed_at.isoformat()})
        return Response(_summary(row))


class WorkdayReopenView(APIView):
    """Reopening lifts the lock for everyone, so it is signed and leaves the
    reason in the audit log. Its own permission (Q18): the chief engineer and
    the administrators hold it, and Usuarios y permisos decides who else."""

    permission_classes = (IsAuthenticated,)

    @tenant_atomic
    def post(self, request, workday_id: int):
        _require(request, REOPEN)
        _reauthenticate(request)
        reason = (request.data.get("reason") or "").strip()
        if not reason:
            raise ValidationError("Indica por qué se reabre la jornada")
        row = _workday(request, workday_id)
        if row.is_open:
            raise ValidationError("La jornada está abierta")
        before = {"closed_at": row.closed_at.isoformat(), "closed_by": row.closed_by_id}
        row.closed_at = None
        row.closed_by = None
        row.save(update_fields=["closed_at", "closed_by"])
        record(request, "workday.reopened", object_type="workday", object_id=row.id,
               before=before, after={"reason": reason})
        return Response(_summary(row))


class ObservationCollectionView(APIView):
    """F3-05: the photo first, whether the finding shows in it, then the text
    — and all of it only once a service of the train has started (Q19)."""

    permission_classes = (IsAuthenticated,)
    parser_classes = (MultiPartParser, FormParser)

    @tenant_atomic
    def post(self, request, workday_id: int):
        actor = _require_any(request, (MANAGE, "workday.register_permit"))
        row = _open_workday(request, workday_id)
        group = _group(request, row)
        if not actor.has(MANAGE) and not allows(request.company_id, group.id, row.date):
            raise ValidationError(
                "El servicio de este conjunto no ha comenzado: faltan su ATS y las firmas de inicio"
            )
        visible = _visible(request.data.get("visible"))
        text = (request.data.get("text") or "").strip()
        try:
            check_observation(has_photo="photo" in request.FILES, visible=visible, text=text)
        except ObservationIncompleteError as cause:
            raise ValidationError(str(cause)) from cause
        observation = FieldObservation.objects.create(
            company_id=request.company_id, workday=row, asset_group=group, visible=bool(visible),
            text=text, created_by=request.user,
        )
        observation.photo = _store(request, "photo", "photo", "field_observation", observation.id,
                                   text[:120], missing="Primero la foto de la observación")
        observation.save(update_fields=["photo"])
        return Response(_observation(observation), status=201)


# ---------------------------------------------------------------- helpers


def _require(request, permission: str):
    actor = build_actor(request.user, request.company_id)
    if not actor.has(permission):
        raise PermissionDenied(f"Falta el permiso {permission}")
    return actor


def _require_any(request, permissions: tuple[str, ...]):
    actor = build_actor(request.user, request.company_id)
    if not any(actor.has(code) for code in permissions):
        raise PermissionDenied(f"Falta el permiso {permissions[-1]}")
    return actor


def _reauthenticate(request) -> None:
    if not request.user.check_password(request.data.get("password") or ""):
        raise PermissionDenied("Clave incorrecta")


def _workday(request, workday_id: int) -> Workday:
    row = (
        Workday.objects.for_company(request.company_id)
        .select_related("plant", "opened_by", "closed_by")
        .filter(id=workday_id)
        .first()
    )
    if row is None:
        raise NotFound("Esa jornada no existe")
    return row


def _open_workday(request, workday_id: int) -> Workday:
    row = _workday(request, workday_id)
    if not row.is_open:
        raise ValidationError("La jornada está cerrada")
    if row.date != timezone.localdate():
        raise ValidationError("Solo se registra en la jornada de hoy")
    return row


def _group(request, row: Workday):
    from modules.assets.models import AssetGroup

    group = AssetGroup.objects.for_company(request.company_id).filter(
        id=request.data.get("asset_group"), sector__area__plant_id=row.plant_id
    ).first()
    if group is None:
        raise ValidationError("Elige un conjunto de esta planta")
    return group


def _visible(raw) -> bool | None:
    if raw in (True, "true", "1", "visible"):
        return True
    if raw in (False, "false", "0", "not_visible"):
        return False
    return None


def _store(request, field, kind, owner_type, owner_id, caption, *, missing):
    from modules.media.infrastructure.uploads import UploadRejectedError, store_upload

    if field not in request.FILES:
        raise ValidationError(missing)
    try:
        asset, _ = store_upload(
            company_id=request.company_id, upload=request.FILES[field], kind=kind,
            owner_type=owner_type, owner_id=owner_id, caption=caption, user=request.user,
        )
    except UploadRejectedError as cause:
        raise ValidationError(str(cause)) from cause
    return asset


def _url(asset) -> str | None:
    if asset is None:
        return None
    from modules.media.infrastructure.local_store import store

    return store().url(asset.original_key)


def _thumb(asset) -> str | None:
    if asset is None:
        return None
    from modules.media.infrastructure.local_store import store

    key = (asset.derivatives or {}).get("thumb", {}).get("key")
    return store().url(key or asset.original_key)


def _name(user) -> str:
    return user.get_full_name() if user else ""


def _summary(row: Workday) -> dict:
    return {
        "id": row.id,
        "plant": {"id": row.plant_id, "name": row.plant.name},
        "date": row.date.isoformat(),
        "is_open": row.is_open,
        "opened_at": row.opened_at.isoformat(),
        "opened_by": _name(row.opened_by),
        "closed_at": row.closed_at.isoformat() if row.closed_at else None,
        "closed_by": _name(row.closed_by),
        "notes": row.notes,
    }


def _work(work) -> dict:
    return {
        "kind": work.kind, "id": work.id, "service": work.service, "order": work.order,
        "group": work.group, "equipment": work.equipment, "people": list(work.people),
        "started_at": work.started_at.isoformat() if work.started_at else None,
        "ended_at": work.ended_at.isoformat() if work.ended_at else None,
    }


def _observation(observation: FieldObservation) -> dict:
    return {
        "id": observation.id,
        "asset_group": {"id": observation.asset_group_id, "name": observation.asset_group.name},
        "visible": observation.visible,
        "text": observation.text,
        "photo_url": _url(observation.photo),
        "photo_thumb": _thumb(observation.photo),
        "created_by": _name(observation.created_by),
        "created_at": observation.created_at.isoformat(),
    }
