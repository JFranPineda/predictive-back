"""Creating the plant from the UI: plant → area → sector → train → equipment.

Each level checks the same three things: the caller may manage assets, the
parent belongs to the caller's company, and the licence still has room.
"""

from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.db.models import ProtectedError
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.assets.domain.asset_code import generate as generate_code
from modules.assets.domain.point_layout import ComponentSpec, next_number, plan_layout
from modules.assets.models import (
    Area,
    AssetGroup,
    AssetGroupKind,
    Equipment,
    MeasurementPoint,
    Plant,
    Sector,
)
from modules.security.application.access import build_actor


class AssetAdminView(APIView):
    permission_classes = [IsAuthenticated]
    required_permission = "assets.manage_equipment"

    def require(self, request) -> None:
        actor = build_actor(request.user, request.company_id)
        if not actor.has(self.required_permission):
            raise PermissionDenied(f"Falta el permiso {self.required_permission}")

    def scoped(self, model, request):
        return model.objects.for_company(request.company_id)


def _check_licence(request, resource: str, current_count: int) -> None:
    """A plan sells a ceiling; this is where it is enforced."""
    from modules.licensing.application.license_service import assert_within_limit

    tenant = getattr(request, "tenant", None)
    if tenant is None:
        return
    if not assert_within_limit(
        tenant.code, resource, current_count, secret=settings.LICENSE_SECRET
    ):
        raise ValidationError(
            f"El plan contratado no permite más {resource}. Contacta con el proveedor."
        )


class PlantCollectionView(AssetAdminView):
    def get(self, request):
        return Response([
            {"id": row.id, "code": row.code, "name": row.name, "address": row.address,
             "is_active": row.is_active, "area_count": row.areas.count()}
            for row in self.scoped(Plant, request).order_by("name")
        ])

    def post(self, request):
        self.require(request)
        name = (request.data.get("name") or "").strip()
        if not name:
            raise ValidationError("El nombre es obligatorio")
        _check_licence(request, "plants", self.scoped(Plant, request).count())

        code = _slug(request.data.get("code") or name)
        if self.scoped(Plant, request).filter(code=code).exists():
            raise ValidationError(f"Ya existe una planta con el código '{code}'")
        plant = Plant.objects.create(
            company_id=request.company_id, code=code, name=name,
            address=(request.data.get("address") or "").strip(),
            timezone=request.data.get("timezone") or "America/Lima",
        )
        return Response({"id": plant.id, "code": plant.code, "name": plant.name}, status=201)


class PlantDetailView(AssetAdminView):
    def patch(self, request, plant_id: int):
        self.require(request)
        plant = _get(self.scoped(Plant, request), plant_id, "planta")
        for field in ("name", "address", "timezone"):
            if field in request.data:
                setattr(plant, field, (request.data.get(field) or "").strip())
        if "is_active" in request.data:
            plant.is_active = bool(request.data["is_active"])
        plant.save()
        return Response({
            "id": plant.id, "code": plant.code, "name": plant.name,
            "address": plant.address, "is_active": plant.is_active,
        })

    def delete(self, request, plant_id: int):
        self.require(request)
        plant = _get(self.scoped(Plant, request), plant_id, "planta")
        return _soft_delete(plant, plant.areas.count(), "áreas")


class AreaCollectionView(AssetAdminView):
    def post(self, request):
        self.require(request)
        plant = self.scoped(Plant, request).filter(id=request.data.get("plant")).first()
        if plant is None:
            raise ValidationError("Debes elegir una planta")
        code = (request.data.get("code") or "").strip()
        name = (request.data.get("name") or "").strip()
        if not code or not name:
            raise ValidationError("El código y el nombre son obligatorios")
        if Area.objects.filter(plant=plant, code=code).exists():
            raise ValidationError(f"El área '{code}' ya existe en esta planta")

        area = Area.objects.create(
            company_id=request.company_id, plant=plant, code=code, name=name,
            criticality=int(request.data.get("criticality") or 3),
            parent=self.scoped(Area, request).filter(id=request.data.get("parent")).first(),
        )
        return Response({"id": area.id, "code": area.code, "name": area.name}, status=201)


class AreaDetailView(AssetAdminView):
    def patch(self, request, area_id: int):
        self.require(request)
        area = _get(self.scoped(Area, request), area_id, "área")
        for field in ("code", "name"):
            if field in request.data:
                setattr(area, field, (request.data.get(field) or "").strip())
        if "criticality" in request.data:
            area.criticality = int(request.data["criticality"])
        if "is_active" in request.data:
            area.is_active = bool(request.data["is_active"])
        area.save()
        return Response({"id": area.id, "code": area.code, "name": area.name})

    def delete(self, request, area_id: int):
        self.require(request)
        area = _get(self.scoped(Area, request), area_id, "área")
        return _soft_delete(area, area.sectors.count(), "sectores")


class SectorCollectionView(AssetAdminView):
    def post(self, request):
        self.require(request)
        area = self.scoped(Area, request).filter(id=request.data.get("area")).first()
        if area is None:
            raise ValidationError("Debes elegir un área")
        name = (request.data.get("name") or "").strip()
        if not name:
            raise ValidationError("El nombre es obligatorio")
        sector = Sector.objects.create(
            company_id=request.company_id, area=area, name=name,
            code=_slug(request.data.get("code") or name)[:40],
        )
        return Response({"id": sector.id, "code": sector.code, "name": sector.name}, status=201)


class SectorDetailView(AssetAdminView):
    def patch(self, request, sector_id: int):
        self.require(request)
        sector = _get(self.scoped(Sector, request), sector_id, "sector")
        if "name" in request.data:
            sector.name = (request.data.get("name") or "").strip()
        sector.save()
        return Response({"id": sector.id, "name": sector.name})

    def delete(self, request, sector_id: int):
        self.require(request)
        sector = _get(self.scoped(Sector, request), sector_id, "sector")
        return _soft_delete(sector, sector.groups.count(), "conjuntos")


class AssetGroupCollectionView(AssetAdminView):
    def get(self, request):
        queryset = (
            self.scoped(AssetGroup, request)
            .select_related("sector__area", "kind")
            .order_by("sector__area__code", "name")
        )
        if request.query_params.get("sector"):
            queryset = queryset.filter(sector_id=request.query_params["sector"])
        return Response([
            {"id": row.id, "code": row.code, "name": row.name,
             "kind": row.kind.code if row.kind else None,
             "kind_id": row.kind_id,
             "kind_name": row.kind.name if row.kind else "",
             "sector": row.sector.name, "sector_id": row.sector_id,
             "area_code": row.sector.area.code,
             "equipment_count": row.equipments.count(),
             "point_count": MeasurementPoint.objects.filter(
                 equipment__asset_group=row
             ).count()}
            for row in queryset[:500]
        ])

    def post(self, request):
        self.require(request)
        sector = self.scoped(Sector, request).filter(id=request.data.get("sector")).first()
        if sector is None:
            raise ValidationError("Debes elegir un sector")
        name = (request.data.get("name") or "").strip()
        if not name:
            raise ValidationError("El nombre es obligatorio")

        code = _unique_code(
            self.scoped(AssetGroup, request),
            _slug(request.data.get("code") or f"{sector.area.code}-{name}")[:58],
        )
        kind = (
            AssetGroupKind.objects.for_company(request.company_id)
            .filter(id=request.data.get("kind"))
            .first()
        )
        group = AssetGroup.objects.create(
            company_id=request.company_id, sector=sector, code=code, name=name, kind=kind,
            criticality=int(request.data.get("criticality") or 3),
        )
        return Response(
            {"id": group.id, "code": group.code, "name": group.name,
             "kind_id": group.kind_id},
            status=201,
        )


class AssetGroupDetailView(AssetAdminView):
    def patch(self, request, group_id: int):
        self.require(request)
        group = _get(self.scoped(AssetGroup, request), group_id, "conjunto")
        if "name" in request.data:
            group.name = (request.data.get("name") or "").strip()
        if "kind" in request.data:
            group.kind = (
                AssetGroupKind.objects.for_company(request.company_id)
                .filter(id=request.data["kind"])
                .first()
            )
        if "criticality" in request.data:
            group.criticality = int(request.data["criticality"])
        group.save()
        return Response({"id": group.id, "name": group.name, "kind_id": group.kind_id})

    def delete(self, request, group_id: int):
        self.require(request)
        group = _get(self.scoped(AssetGroup, request), group_id, "conjunto")
        return _soft_delete(group, group.equipments.count(), "equipos")


class EquipmentCollectionView(AssetAdminView):
    @transaction.atomic
    def post(self, request):
        self.require(request)
        group = self.scoped(AssetGroup, request).filter(id=request.data.get("asset_group")).first()
        if group is None:
            raise ValidationError("Debes elegir un conjunto rotativo")
        name = (request.data.get("name") or "").strip()
        equipment_type = request.data.get("equipment_type")
        if not name or not equipment_type:
            raise ValidationError("El nombre y el tipo de equipo son obligatorios")
        _check_licence(request, "equipment", self.scoped(Equipment, request).count())

        taken = set(self.scoped(Equipment, request).values_list("asset_code", flat=True))
        component = _component_for(group, request.data.get("group_component"), equipment_type)
        equipment = Equipment.objects.create(
            company_id=request.company_id,
            asset_group=group,
            asset_code=generate_code(
                area_code=group.sector.area.code,
                equipment_type=equipment_type,
                client_tag=(request.data.get("client_tag") or "").strip() or None,
                taken=taken,
            ),
            client_tag=(request.data.get("client_tag") or "").strip(),
            name=name,
            equipment_type=equipment_type,
            position_in_group=(
                request.data.get("position_in_group")
                or (component.position if component else "driven")
            ),
            group_component=component,
            order_in_group=(
                component.order if component else group.equipments.count()
            ),
            monitoring_frequency=request.data.get("monitoring_frequency") or "monthly",
            applied_standard_id=request.data.get("applied_standard") or None,
            machine_class_id=request.data.get("machine_class") or None,
        )

        # Points are what readings hang off; an equipment without them cannot
        # be measured, so the usual layout is offered up front.
        if request.data.get("generate_points", True):
            _generate_points(equipment, int(request.data.get("first_point") or 0) or None)

        return Response({
            "id": equipment.id, "asset_code": equipment.asset_code,
            "client_tag": equipment.client_tag, "name": equipment.name,
            "point_count": equipment.points.count(),
        }, status=201)


class EquipmentDetailView(AssetAdminView):
    def patch(self, request, equipment_id: int):
        self.require(request)
        equipment = _get(self.scoped(Equipment, request), equipment_id, "equipo")
        for field in ("name", "client_tag", "equipment_type", "position_in_group",
                      "monitoring_frequency"):
            if field in request.data:
                setattr(equipment, field, (request.data.get(field) or "").strip())
        if "applied_standard" in request.data:
            equipment.applied_standard_id = request.data["applied_standard"] or None
        if "machine_class" in request.data:
            equipment.machine_class_id = request.data["machine_class"] or None
        equipment.save()
        return Response({"id": equipment.id, "name": equipment.name})

    def delete(self, request, equipment_id: int):
        self.require(request)
        equipment = _get(self.scoped(Equipment, request), equipment_id, "equipo")
        readings = MeasurementPoint.objects.filter(equipment=equipment).count()
        return _soft_delete(equipment, readings, "puntos")


class PointCollectionView(AssetAdminView):
    required_permission = "assets.manage_point"

    def post(self, request):
        self.require(request)
        equipment = self.scoped(Equipment, request).filter(
            id=request.data.get("equipment")
        ).first()
        if equipment is None:
            raise ValidationError("Debes elegir un equipo")
        number = int(request.data.get("number") or _next_point_number(equipment.asset_group_id))
        axis = request.data.get("axis") or "N"
        clash = (
            MeasurementPoint.objects.filter(
                equipment__asset_group_id=equipment.asset_group_id, number=number, axis=axis
            )
            .select_related("equipment")
            .first()
        )
        if clash is not None:
            raise ValidationError(
                f"El punto {number}{axis} ya existe en el conjunto, en {clash.equipment.name}"
            )

        point = MeasurementPoint.objects.create(
            company_id=request.company_id, equipment=equipment, number=number, axis=axis,
            side=request.data.get("side") or "custom",
            point_type=request.data.get("point_type") or "bearing",
        )
        return Response({"id": point.id, "label": point.label}, status=201)


class PointDetailView(AssetAdminView):
    required_permission = "assets.manage_point"

    def patch(self, request, point_id: int):
        """Correcting a point, instead of deleting and rebuilding it.

        Rebuilding takes its readings with it, so a layout typed with the
        wrong side used to cost a year of history.
        """
        self.require(request)
        point = _get(self.scoped(MeasurementPoint, request), point_id, "punto")

        number = request.data.get("number")
        axis = request.data.get("axis") or point.axis
        if number is not None or "axis" in request.data:
            number = int(number if number is not None else point.number)
            clash = (
                MeasurementPoint.objects.filter(
                    equipment__asset_group_id=point.equipment.asset_group_id,
                    number=number, axis=axis,
                )
                .exclude(id=point.id)
                .select_related("equipment")
                .first()
            )
            if clash is not None:
                raise ValidationError(
                    f"El punto {number}{axis} ya existe en el conjunto, en {clash.equipment.name}"
                )
            point.number, point.axis = number, axis
            # `label` is derived; letting it go stale is how a grid ends up
            # printing 3H for a point that is now 4V.
            point.label = f"{point.number}{point.axis if point.axis != 'N' else ''}"

        for field in ("side", "point_type"):
            if field in request.data:
                setattr(point, field, request.data.get(field) or getattr(point, field))
        if "is_active" in request.data:
            point.is_active = bool(request.data["is_active"])
        point.save()
        return Response({
            "id": point.id, "label": point.label, "number": point.number, "axis": point.axis,
            "side": point.side, "point_type": point.point_type, "is_active": point.is_active,
        })

    def delete(self, request, point_id: int):
        self.require(request)
        point = _get(self.scoped(MeasurementPoint, request), point_id, "punto")
        if point.readings.exists():
            point.is_active = False
            point.save(update_fields=["is_active"])
            return Response({"id": point.id, "is_active": False, "deactivated": True})
        point.delete()
        return Response(status=204)


def _generate_points(equipment: Equipment, first: int | None = None) -> None:
    """Lays out the points of one machine, continuing the train's numbering.

    The component of the kind decides how many there are — a gearbox read on
    four points is not an exception, it is most of the reports.
    """

    component = equipment.group_component
    spec = ComponentSpec(
        label=component.label if component else equipment.name,
        point_count=component.point_count if component else 2,
        position=equipment.position_in_group,
        equipment_type=equipment.equipment_type,
    )
    start = first if first else _next_point_number(equipment.asset_group_id)
    MeasurementPoint.objects.bulk_create([
        MeasurementPoint(
            company_id=equipment.company_id,
            equipment=equipment,
            number=row.number,
            axis=row.axis,
            side=row.side,
            point_type="bearing",
        )
        for row in plan_layout([spec], first_number=start)
    ])


def _component_for(group: AssetGroup, component_id, equipment_type: str):
    """Which slot of the kind this machine fills.

    Chosen explicitly when the form says so; otherwise the first slot of that
    type still free, because a train with two bearing housings must not give
    both of them the same points.
    """

    if group.kind_id is None:
        return None
    components = list(group.kind.components.all())
    if component_id:
        return next((row for row in components if row.id == int(component_id)), None)
    used = set(
        group.equipments.exclude(group_component=None).values_list("group_component_id", flat=True)
    )
    free = [row for row in components if row.id not in used]
    return next((row for row in free if row.equipment_type == equipment_type), None)


def _next_point_number(group_id: int) -> int:
    """Point numbers run across the whole train, never per machine: the codes
    the analyst writes (`HV-7`) carry no component, so a repeat is ambiguous."""

    return next_number(
        MeasurementPoint.objects.filter(equipment__asset_group_id=group_id).values_list(
            "number", flat=True
        )
    )


def _get(queryset, pk: int, label: str):
    row = queryset.filter(id=pk).first()
    if row is None:
        raise ValidationError(f"Ese {label} no existe")
    return row


def _soft_delete(row, dependants: int, label: str):
    """History is never destroyed on a delete button.

    Anything with children or readings behind it is deactivated instead, which
    keeps every past report readable.
    """
    if dependants:
        row.is_active = False
        row.save(update_fields=["is_active"])
        return Response({"id": row.id, "is_active": False, "deactivated": True,
                         "reason": f"tiene {dependants} {label}"})
    try:
        row.delete()
    except ProtectedError:
        row.is_active = False
        row.save(update_fields=["is_active"])
        return Response({"id": row.id, "is_active": False, "deactivated": True})
    return Response(status=204)


def _slug(value: str) -> str:
    cleaned = "".join(c if c.isalnum() else "-" for c in (value or "").strip().lower())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-") or "x"


def _unique_code(queryset, candidate: str) -> str:
    if not queryset.filter(code=candidate).exists():
        return candidate
    for suffix in range(2, 9999):
        alternative = f"{candidate[:54]}-{suffix}"
        if not queryset.filter(code=alternative).exists():
            return alternative
    raise ValidationError("No se pudo generar un código único")
