"""A service of the day (Q17, Q19): its ATS, the signatures that start it,
an administrator's unlock, and the signed close that sets its final hour."""

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
    CLOSE_SERVICE,
    IPERC_LEVELS,
    MANAGE,
    RISK_CATEGORIES,
    ROLE_LABELS,
    START_ROLES,
    UNLOCK_SERVICE,
    Ats,
    CrewMember,
    ServiceNotClosableError,
    Step,
    ats_missing,
    check_closable,
    items_of,
    job_started,
)
from modules.workday.models import JobSignature, ServiceJob, Workday

REGISTER = "workday.register_permit"
HEADER_FIELDS = ("activity", "holder", "unit", "area", "zone", "ppe", "tools")
MAX_STEPS = 60


class JobCollectionView(APIView):
    """`GET|POST workdays/<id>/jobs/` — the day's services; a new one names
    its train and, when there is one, the order it works for."""

    permission_classes = (IsAuthenticated,)

    def get(self, request, workday_id: int):
        _require_any(request, (MANAGE, REGISTER, "workday.view_permits"))
        workday = _workday(request, workday_id)
        return Response([job_summary(job) for job in _jobs().filter(workday=workday)])

    @tenant_atomic
    def post(self, request, workday_id: int):
        _require_any(request, (MANAGE, REGISTER))
        workday = _workday(request, workday_id)
        if not workday.is_open:
            raise ValidationError("La jornada está cerrada")
        if workday.date != timezone.localdate():
            raise ValidationError("Solo se registran servicios en la jornada de hoy")
        group = _group(request, workday)
        order = _order(request, workday)
        job = ServiceJob.objects.create(
            company_id=request.company_id,
            workday=workday,
            asset_group=group,
            service_order=order,
            activity=(request.data.get("activity") or "").strip()[:200],
            area=group.sector.area.name[:120],
            created_by=request.user,
        )
        record(
            request,
            "workday.job_created",
            object_type="service_job",
            object_id=job.id,
            after={"asset_group": group.id, "service_order": order.id if order else None},
        )
        return Response(job_detail(_job(request, job.id)), status=201)


class JobDetailView(APIView):
    """`GET|PATCH|DELETE workday-jobs/<id>/` — the ATS is edited until the
    service closes; a service is deleted only before it starts."""

    permission_classes = (IsAuthenticated,)

    def get(self, request, job_id: int):
        _require_any(request, (MANAGE, REGISTER, "workday.view_permits"))
        return Response(job_detail(_job(request, job_id)))

    @tenant_atomic
    def patch(self, request, job_id: int):
        _require_any(request, (MANAGE, REGISTER))
        job = _editable(request, job_id)
        for field in HEADER_FIELDS:
            if field in request.data:
                setattr(job, field, (request.data.get(field) or "").strip())
        if "risk_category" in request.data:
            category = request.data.get("risk_category") or ""
            if category and category not in RISK_CATEGORIES:
                raise ValidationError("Categoría de riesgo desconocida")
            job.risk_category = category
        if "steps" in request.data:
            job.steps = _steps(request.data.get("steps"))
        job.save()
        return Response(job_detail(_job(request, job_id)))

    @tenant_atomic
    def delete(self, request, job_id: int):
        _require_any(request, (MANAGE, REGISTER))
        job = _editable(request, job_id)
        if job.started_at is not None:
            raise ValidationError("Un servicio que ya comenzó no se elimina: ciérralo")
        record(request, "workday.job_deleted", object_type="service_job", object_id=job.id)
        job.delete()
        return Response(status=204)


class JobCrewView(APIView):
    """`POST workday-jobs/<id>/crew/` — one person of the ATS's crew, listed
    before signing. `DELETE workday-jobs/<id>/crew/<signature_id>/`."""

    permission_classes = (IsAuthenticated,)

    @tenant_atomic
    def post(self, request, job_id: int):
        _require_any(request, (MANAGE, REGISTER))
        job = _editable(request, job_id)
        name = (request.data.get("name") or "").strip()
        if not name:
            raise ValidationError("Escribe el nombre de la persona")
        JobSignature.objects.create(
            company_id=request.company_id,
            job=job,
            role="crew",
            name=name[:160],
            position=(request.data.get("position") or "").strip()[:120],
            user_id=request.data.get("user") or None,
        )
        return Response(job_detail(_job(request, job_id)), status=201)

    @tenant_atomic
    def delete(self, request, job_id: int, signature_id: int):
        _require_any(request, (MANAGE, REGISTER))
        job = _editable(request, job_id)
        deleted, _ = JobSignature.objects.filter(job=job, id=signature_id, role="crew").delete()
        if not deleted:
            raise NotFound("Esa persona no está en el ATS")
        return Response(job_detail(_job(request, job_id)))


class JobSignView(APIView):
    """`POST workday-jobs/<id>/sign/` (multipart): a signature drawn on the
    screen. `role` is one of the three start roles, or `crew` with the
    `signature` id of the person signing. The third start signature starts
    the service (Q19)."""

    permission_classes = (IsAuthenticated,)
    parser_classes = (MultiPartParser, FormParser)

    @tenant_atomic
    def post(self, request, job_id: int):
        _require_any(request, (MANAGE, REGISTER))
        job = _editable(request, job_id)
        role = request.data.get("role")
        if role == "crew":
            row = JobSignature.objects.filter(job=job, role="crew", id=request.data.get("signature")).first()
            if row is None:
                raise ValidationError("Esa persona no está en el ATS")
        elif role in START_ROLES:
            if job.started_at is not None:
                raise ValidationError("El servicio ya comenzó: sus firmas de inicio no se cambian")
            name = (request.data.get("name") or "").strip()
            if not name:
                raise ValidationError(f"Escribe el nombre del {ROLE_LABELS[role].lower()}")
            row = JobSignature.objects.filter(job=job, role=role).first() or JobSignature(
                company_id=request.company_id, job=job, role=role
            )
            row.name = name[:160]
            row.position = (request.data.get("position") or "").strip()[:120]
        else:
            raise ValidationError("Rol de firma desconocido")

        row.image = _store(request, job, f"Firma · {ROLE_LABELS[role]} · {row.name}")
        row.signed_at = timezone.now()
        row.captured_by = request.user
        row.save()
        record(
            request,
            "workday.job_signed",
            object_type="service_job",
            object_id=job.id,
            after={"role": role, "name": row.name},
        )

        signed = JobSignature.objects.filter(job=job, signed_at__isnull=False).values_list("role", flat=True)
        if job.started_at is None and job_started(signed, unlocked=False):
            job.started_at = timezone.now()
            job.save(update_fields=["started_at"])
            record(request, "workday.job_started", object_type="service_job", object_id=job.id)
        return Response(job_detail(_job(request, job_id)))


class JobUnlockView(APIView):
    """`POST workday-jobs/<id>/unlock/` — an administrator lets the work start
    without the three signatures, and says why (Q19)."""

    permission_classes = (IsAuthenticated,)

    @tenant_atomic
    def post(self, request, job_id: int):
        _require_any(request, (UNLOCK_SERVICE,))
        job = _editable(request, job_id)
        if job.started_at is not None:
            raise ValidationError("El servicio ya comenzó")
        reason = (request.data.get("reason") or "").strip()
        if not reason:
            raise ValidationError("Indica por qué se desbloquea sin las firmas de inicio")
        now = timezone.now()
        job.started_at = now
        job.unlocked_at = now
        job.unlocked_by = request.user
        job.unlock_reason = reason
        job.save(update_fields=["started_at", "unlocked_at", "unlocked_by", "unlock_reason"])
        record(
            request,
            "workday.job_unlocked",
            object_type="service_job",
            object_id=job.id,
            after={"reason": reason},
        )
        return Response(job_detail(_job(request, job_id)))


class JobCloseView(APIView):
    """`POST workday-jobs/<id>/close/` — the chief engineer's (or an
    administrator's) key over a complete, signed ATS: its time is the
    service's final hour (Q19)."""

    permission_classes = (IsAuthenticated,)

    @tenant_atomic
    def post(self, request, job_id: int):
        _require_any(request, (CLOSE_SERVICE,))
        if not request.user.check_password(request.data.get("password") or ""):
            raise PermissionDenied("Clave incorrecta")
        job = _job(request, job_id)
        try:
            check_closable(
                started=job.started_at is not None, closed=job.is_closed, missing=ats_missing(_ats(job))
            )
        except ServiceNotClosableError as cause:
            raise ValidationError(str(cause)) from cause
        job.closed_at = timezone.now()
        job.closed_by = request.user
        job.save(update_fields=["closed_at", "closed_by"])
        record(
            request,
            "workday.job_closed",
            object_type="service_job",
            object_id=job.id,
            after={"closed_at": job.closed_at.isoformat()},
        )
        return Response(job_detail(_job(request, job_id)))


# ---------------------------------------------------------------- helpers


def _require_any(request, permissions: tuple[str, ...]):
    actor = build_actor(request.user, request.company_id)
    if not any(actor.has(code) for code in permissions):
        raise PermissionDenied(f"Falta el permiso {permissions[-1]}")
    return actor


def _workday(request, workday_id: int) -> Workday:
    row = Workday.objects.for_company(request.company_id).filter(id=workday_id).first()
    if row is None:
        raise NotFound("Esa jornada no existe")
    return row


def _jobs():
    return ServiceJob.objects.select_related(
        "workday", "asset_group", "service_order__technique", "closed_by", "unlocked_by"
    ).prefetch_related("signatures__image")


def _job(request, job_id: int) -> ServiceJob:
    job = _jobs().filter(company_id=request.company_id, id=job_id).first()
    if job is None:
        raise NotFound("Ese servicio no existe")
    return job


def _editable(request, job_id: int) -> ServiceJob:
    job = _job(request, job_id)
    if job.is_closed:
        raise ValidationError("El servicio está cerrado")
    if not job.workday.is_open:
        raise ValidationError("La jornada está cerrada")
    return job


def _group(request, workday: Workday):
    from modules.assets.models import AssetGroup

    group = (
        AssetGroup.objects.for_company(request.company_id)
        .select_related("sector__area")
        .filter(id=request.data.get("asset_group"), sector__area__plant_id=workday.plant_id)
        .first()
    )
    if group is None:
        raise ValidationError("Elige un conjunto de esta planta")
    return group


def _order(request, workday: Workday):
    order_id = request.data.get("service_order")
    if not order_id:
        return None
    from modules.services.models import ServiceOrder

    order = (
        ServiceOrder.objects.for_company(request.company_id)
        .filter(id=order_id, plant_id=workday.plant_id)
        .first()
    )
    if order is None:
        raise ValidationError("Esa orden no es de esta planta")
    return order


def _steps(raw) -> list[dict]:
    if not isinstance(raw, list) or len(raw) > MAX_STEPS:
        raise ValidationError(f"Los pasos llegan como una lista de hasta {MAX_STEPS}")
    steps = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValidationError("Cada paso es un objeto")
        level = (item.get("level") or "").strip().upper()
        if level and level not in IPERC_LEVELS:
            raise ValidationError("La evaluación IPERC es A, M o B")
        score = item.get("score")
        try:
            score = int(score) if score not in (None, "") else None
        except (TypeError, ValueError) as cause:
            raise ValidationError("El puntaje IPERC es un número entero") from cause
        steps.append(
            {
                "step": str(item.get("step") or "").strip()[:300],
                "hazard": str(item.get("hazard") or "").strip()[:200],
                "risk": str(item.get("risk") or "").strip()[:200],
                "level": level,
                "score": score,
                "controls": str(item.get("controls") or "").strip()[:500],
            }
        )
    return steps


def _store(request, job: ServiceJob, caption: str):
    from modules.media.infrastructure.uploads import UploadRejectedError, store_upload

    if "image" not in request.FILES:
        raise ValidationError("Falta el dibujo de la firma")
    try:
        asset, _ = store_upload(
            company_id=request.company_id,
            upload=request.FILES["image"],
            kind="signature",
            owner_type="service_job",
            owner_id=job.id,
            caption=caption[:120],
            user=request.user,
        )
    except UploadRejectedError as cause:
        raise ValidationError(str(cause)) from cause
    return asset


def _ats(job: ServiceJob) -> Ats:
    crew = [s for s in job.signatures.all() if s.role == "crew"]
    return Ats(
        activity=job.activity,
        holder=job.holder,
        area=job.area,
        zone=job.zone,
        risk_category=job.risk_category,
        ppe=job.ppe,
        tools=job.tools,
        steps=tuple(
            Step(
                s.get("step", ""),
                s.get("hazard", ""),
                s.get("risk", ""),
                s.get("level", ""),
                s.get("score"),
                s.get("controls", ""),
            )
            for s in job.steps or []
        ),
        crew=tuple(CrewMember(member.name, member.signed_at is not None) for member in crew),
    )


def _status(job: ServiceJob) -> str:
    if job.is_closed:
        return "closed"
    return "in_progress" if job.started_at else "pending_start"


def _url(asset) -> str | None:
    if asset is None:
        return None
    from modules.media.infrastructure.local_store import store

    return store().url(asset.original_key)


def _name(user) -> str:
    return user.get_full_name() if user else ""


def _signature(row: JobSignature | None, role: str) -> dict:
    return {
        "id": row.id if row else None,
        "role": role,
        "label": ROLE_LABELS[role],
        "name": row.name if row else "",
        "position": row.position if row else "",
        "signed_at": row.signed_at.isoformat() if row and row.signed_at else None,
        "image_url": _url(row.image) if row else None,
    }


def job_summary(job: ServiceJob) -> dict:
    signed = {s.role for s in job.signatures.all() if s.signed_at}
    order = job.service_order
    return {
        "id": job.id,
        "workday_id": job.workday_id,
        "asset_group": {"id": job.asset_group_id, "name": job.asset_group.name},
        "service_order": (
            {"id": order.id, "code": order.code, "technique": order.technique.name} if order else None
        ),
        "activity": job.activity,
        "status": _status(job),
        "start_signed": [role for role in START_ROLES if role in signed],
        "unlocked": job.unlocked_at is not None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "closed_at": job.closed_at.isoformat() if job.closed_at else None,
        "closed_by": _name(job.closed_by),
    }


def job_detail(job: ServiceJob) -> dict:
    by_role = {s.role: s for s in job.signatures.all() if s.role != "crew"}
    crew = [s for s in job.signatures.all() if s.role == "crew"]
    steps = job.steps or []
    items = items_of(Step(s.get("step", ""), "", "", "", None, "") for s in steps)
    missing = ats_missing(_ats(job))
    return {
        **job_summary(job),
        "workday": {"date": job.workday.date.isoformat(), "is_open": job.workday.is_open},
        "holder": job.holder,
        "unit": job.unit,
        "area": job.area,
        "zone": job.zone,
        "risk_category": job.risk_category,
        "ppe": job.ppe,
        "tools": job.tools,
        "steps": [{**step, "item": item} for step, item in zip(steps, items, strict=True)],
        "start_signatures": [_signature(by_role.get(role), role) for role in START_ROLES],
        "crew": [_signature(member, "crew") for member in crew],
        "unlock": (
            {"by": _name(job.unlocked_by), "at": job.unlocked_at.isoformat(), "reason": job.unlock_reason}
            if job.unlocked_at
            else None
        ),
        "missing": missing,
        "can_close": job.started_at is not None and not job.is_closed and not missing,
    }
