"""The catalogue of UT en rodillos: groups of rollers and their rollers.

A group is an ordinary train of kind Rodillos and a roller an ordinary
equipment with six points; this is where the crew creates, renames, retires
and removes them without going through Estructura. A roller that was measured
is retired, never deleted: its thicknesses belong to orders already reported.
"""

from __future__ import annotations

from django.conf import settings
from django.db.models import Count
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.core.infrastructure.audit import record
from modules.core.infrastructure.transactions import tenant_atomic
from modules.ut_rollers.domain.rollers import POINTS
from modules.ut_rollers.infrastructure.setup import KIND
from modules.ut_rollers.interfaces.common import require

MAX_ROLLERS = 200


class RollerGroupsView(APIView):
    """`GET ut-rollers/groups/` — the trains of kind Rodillos.
    `POST` with `{"name", "sector"}` — a new one, without leaving the screen
    for Estructura: its kind is always Rodillos."""

    permission_classes = (IsAuthenticated,)

    @tenant_atomic
    def post(self, request):
        actor = require(request, "ut_rollers.manage_rollers")
        from modules.assets.models import AssetGroup, AssetGroupKind, Sector

        sector = (
            Sector.objects.for_company(request.company_id)
            .select_related("area")
            .filter(id=request.data.get("sector"))
            .first()
        )
        if sector is None:
            raise ValidationError("Elige el sector donde está el grupo de rodillos")
        if not actor.may_reach_area(sector.area_id):
            raise PermissionDenied("Ese sector está fuera de tu alcance")
        name = (request.data.get("name") or "").strip()
        if not name:
            raise ValidationError("El nombre es obligatorio, p. ej. «Secadores grupo 1»")
        kind = AssetGroupKind.objects.for_company(request.company_id).filter(code=KIND).first()
        if kind is None:
            raise ValidationError("Falta el tipo de conjunto Rodillos: reinstala el módulo")

        groups = AssetGroup.objects.for_company(request.company_id)
        code = _free_code(groups, slugify(f"{sector.area.code}-{name}")[:58])
        group = AssetGroup.objects.create(
            company_id=request.company_id, sector=sector, code=code, name=name, kind=kind
        )
        record(request, "ut_rollers.group_created", object_type="asset_group", object_id=group.id,
               after={"name": name, "sector": sector.id})
        return Response({"id": group.id, "name": group.name, "rollers": 0}, status=201)

    def get(self, request):
        actor = require(request, "ut_rollers.view")
        from modules.assets.models import AssetGroup

        groups = (
            AssetGroup.objects.for_company(request.company_id)
            .filter(kind__code=KIND, is_active=True)
            .select_related("sector")
        )
        if actor.area_ids is not None:
            groups = groups.filter(sector__area_id__in=actor.area_ids)
        return Response(
            [
                {
                    "id": group.id,
                    "name": group.name,
                    "sector": group.sector.name,
                    "rollers": group.equipments.filter(
                        equipment_type="roller", retired_at__isnull=True
                    ).count(),
                }
                for group in groups.order_by("name")
            ]
        )


class RollerCollectionView(APIView):
    """`GET ut-rollers/groups/<id>/rollers/` — every roller of the group,
    retired ones included, with how much was measured on each.

    `POST` with `{"numbers": [1, 2, …]}` adds rollers.

    All or nothing against the plan: a load that does not fit whole creates
    none of it (V3-36). Numbers already in the group are skipped, so the call
    can be repeated.
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request, group_id: int):
        require(request, "ut_rollers.view")
        group = _group(request, group_id)
        return Response([_roller(row) for row in _rollers(group)])

    @tenant_atomic
    def post(self, request, group_id: int):
        actor = require(request, "ut_rollers.manage_rollers")
        from modules.assets.models import AssetGroup, Equipment, MeasurementPoint

        group = (
            AssetGroup.objects.for_company(request.company_id)
            .select_related("sector__area", "kind")
            .filter(id=group_id, kind__code=KIND)
            .first()
        )
        if group is None:
            raise ValidationError("Ese conjunto no existe o no es de rodillos")
        if not actor.may_reach_area(group.sector.area_id):
            raise PermissionDenied("Ese conjunto está fuera de tu alcance")

        numbers = sorted({int(n) for n in request.data.get("numbers") or [] if str(n).strip()})
        if not numbers or len(numbers) > MAX_ROLLERS or min(numbers) < 1:
            raise ValidationError(f"Indica de 1 a {MAX_ROLLERS} números de rodillo")
        existing = set(
            group.equipments.filter(equipment_type="roller").values_list("order_in_group", flat=True)
        )
        new = [number for number in numbers if number not in existing]
        _ensure_plan_room(request, len(new))

        from modules.assets.domain.asset_code import generate as generate_code

        component = group.kind.components.first()
        taken = set(Equipment.objects.for_company(request.company_id).values_list("asset_code", flat=True))
        for number in new:
            code = generate_code(
                area_code=group.sector.area.code,
                equipment_type="roller",
                client_tag=None,
                taken=taken,
            )
            taken.add(code)
            roller = Equipment.objects.create(
                company_id=request.company_id,
                asset_group=group,
                asset_code=code,
                client_tag=f"{group.name} {number}"[:60],
                name=f"POLÍN {number}",
                equipment_type="roller",
                position_in_group="driven",
                group_component=component,
                order_in_group=number,
                monitoring_frequency="on_demand",
                lubrication_type="none",
            )
            for point in range(1, POINTS + 1):
                MeasurementPoint.objects.create(
                    company_id=request.company_id,
                    equipment=roller,
                    number=point,
                    axis="N",
                    side="custom",
                    point_type="bearing",
                    label=f"P{point}",
                )
        record(
            request,
            "ut_rollers.rollers_added",
            object_type="asset_group",
            object_id=group.id,
            after={"numbers": new},
        )
        return Response({"created": new, "skipped": sorted(existing & set(numbers))}, status=201)


def _ensure_plan_room(request, adding: int) -> None:
    tenant = getattr(request, "tenant", None)
    if tenant is None or adding == 0:
        return
    from modules.assets.infrastructure.plan_counts import equipment_in_plan
    from modules.licensing.application.license_service import PlanLimitReachedError, ensure_room

    try:
        ensure_room(
            tenant.code,
            "equipment",
            equipment_in_plan(request.company_id),
            secret=settings.LICENSE_SECRET,
            adding=adding,
        )
    except PlanLimitReachedError as cause:
        record(request, "license.limit_reached", object_type="equipment", after={"adding": adding})
        raise ValidationError(str(cause)) from cause


class RollerGroupDetailView(APIView):
    """`PATCH ut-rollers/groups/<id>/` renames; `DELETE` removes a group that
    never had a roller — one with rollers keeps its history."""

    permission_classes = (IsAuthenticated,)

    def patch(self, request, group_id: int):
        require(request, "ut_rollers.manage_rollers")
        group = _group(request, group_id)
        name = (request.data.get("name") or "").strip()
        if not name:
            raise ValidationError("El nombre es obligatorio")
        before = group.name
        group.name = name
        group.save(update_fields=["name"])
        record(request, "ut_rollers.group_renamed", object_type="asset_group", object_id=group.id,
               before={"name": before}, after={"name": name})
        return Response({"id": group.id, "name": group.name})

    @tenant_atomic
    def delete(self, request, group_id: int):
        require(request, "ut_rollers.manage_rollers")
        group = _group(request, group_id)
        if group.equipments.exists():
            raise ValidationError(
                "El grupo tiene rodillos: retíralos o elimínalos primero. Uno ya medido solo se retira."
            )
        record(request, "ut_rollers.group_deleted", object_type="asset_group", object_id=group.id,
               before={"name": group.name})
        group.delete()
        return Response(status=204)


class RollerDetailView(APIView):
    """`PATCH ut-rollers/rollers/<id>/` with `{"retired": bool}` takes a
    roller out of (or back into) the sheets; `DELETE` removes one that was
    never measured."""

    permission_classes = (IsAuthenticated,)

    def patch(self, request, roller_id: int):
        require(request, "ut_rollers.manage_rollers")
        roller = _roller_of(request, roller_id)
        if "retired" in request.data:
            retired = bool(request.data["retired"])
            if retired != (roller.retired_at is not None):
                _plan_room_to_restore(request, retired)
                roller.retired_at = timezone.now() if retired else None
                roller.save(update_fields=["retired_at"])
                record(request, "ut_rollers.roller_retired" if retired else "ut_rollers.roller_restored",
                       object_type="equipment", object_id=roller.id)
        return Response(_roller(_annotated(roller)))

    @tenant_atomic
    def delete(self, request, roller_id: int):
        require(request, "ut_rollers.manage_rollers")
        roller = _annotated(_roller_of(request, roller_id))
        if _measured(roller):
            raise ValidationError(
                f"El rodillo {roller.order_in_group} tiene espesores registrados: retíralo en lugar de "
                "eliminarlo, así sus órdenes siguen completas."
            )
        record(request, "ut_rollers.roller_deleted", object_type="equipment", object_id=roller.id,
               before={"number": roller.order_in_group, "group": roller.asset_group_id})
        roller.delete()
        return Response(status=204)


def _group(request, group_id: int):
    from modules.assets.models import AssetGroup

    group = (
        AssetGroup.objects.for_company(request.company_id)
        .select_related("sector__area", "kind")
        .filter(id=group_id, kind__code=KIND)
        .first()
    )
    if group is None:
        raise ValidationError("Ese conjunto no existe o no es de rodillos")
    actor = require(request, "ut_rollers.view")
    if not actor.may_reach_area(group.sector.area_id):
        raise PermissionDenied("Ese conjunto está fuera de tu alcance")
    return group


def _rollers(group):
    from modules.assets.models import Equipment

    # Thicknesses, findings and journal sheets all hang off the roller: any
    # of them makes it part of an order already reported.
    return (
        Equipment.objects.filter(asset_group=group, equipment_type="roller")
        .annotate(
            readings=Count("points__readings", distinct=True),
            findings=Count("ut_indications", distinct=True),
            journals=Count("ut_journals", distinct=True),
        )
        .order_by("order_in_group", "id")
    )


def _measured(row) -> bool:
    return bool(row.readings or row.findings or row.journals)


def _roller_of(request, roller_id: int):
    from modules.assets.models import Equipment

    roller = (
        Equipment.objects.for_company(request.company_id)
        .filter(id=roller_id, equipment_type="roller", asset_group__kind__code=KIND)
        .select_related("asset_group__sector")
        .first()
    )
    if roller is None:
        raise ValidationError("Ese rodillo no existe")
    _group(request, roller.asset_group_id)
    return roller


def _annotated(roller):
    return _rollers(roller.asset_group).get(id=roller.id)


def _roller(row) -> dict:
    return {
        "id": row.id,
        "number": row.order_in_group,
        "code": row.asset_code,
        "tag": row.client_tag,
        "readings": row.readings,
        "measured": _measured(row),
        "retired": row.retired_at is not None,
    }


def _plan_room_to_restore(request, retiring: bool) -> None:
    """A roller brought back counts against the plan again."""
    if not retiring:
        _ensure_plan_room(request, 1)


def _free_code(groups, base: str) -> str:
    code, suffix = base, 2
    while groups.filter(code=code).exists():
        code = f"{base[:55]}-{suffix}"
        suffix += 1
    return code
