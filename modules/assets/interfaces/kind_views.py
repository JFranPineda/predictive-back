"""Machine-train kinds and their measuring layout.

The layout is the part that matters: a kind says a motor-pump train is
measured on points 1 and 2 of the motor and 3 and 4 of the pump, three axes
each, with velocity everywhere and envelope and temperature on the horizontal.
Creating a train from that kind produces exactly the rows the customer's
report expects, instead of six generic points somebody has to rename.
"""

from __future__ import annotations

from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.assets.models import (
    AssetGroup,
    AssetGroupComponent,
    AssetGroupKind,
    MeasurementPoint,
    PointTemplate,
)
from modules.security.application.access import build_actor

AXES = ("H", "V", "A", "N")
SIDES = ("free_end", "coupling_end", "opposite_coupling", "inboard", "outboard", "custom")


class KindView(APIView):
    permission_classes = [IsAuthenticated]

    def require(self, request, permission: str = "assets.manage_equipment") -> None:
        actor = build_actor(request.user, request.company_id)
        if not actor.has(permission):
            raise PermissionDenied(f"Falta el permiso {permission}")

    def scoped(self, request):
        return AssetGroupKind.objects.for_company(request.company_id)


class KindCollectionView(KindView):
    def get(self, request):
        language = getattr(request, "language", "es")
        rows = (
            self.scoped(request)
            .prefetch_related("components", "point_templates__component", "groups")
            .order_by("name")
        )
        return Response([_payload(row, language) for row in rows])

    @transaction.atomic
    def post(self, request):
        self.require(request)
        name = (request.data.get("name") or "").strip()
        if not name:
            raise ValidationError("El nombre es obligatorio")
        code = _slug(request.data.get("code") or name)
        if self.scoped(request).filter(code=code).exists():
            raise ValidationError(f"Ya existe un tipo con el código '{code}'")

        kind = AssetGroupKind.objects.create(
            company_id=request.company_id, code=code, name=name,
            description=(request.data.get("description") or "").strip(),
            translations={"name": {"es": name}},
        )
        _replace_components(kind, request.data.get("components") or [])
        if request.data.get("point_templates") is not None:
            _replace_templates(kind, request.data["point_templates"])
        else:
            # A kind with no layout cannot produce a report, so the standard
            # two-points-per-machine arrangement is offered from the start.
            _default_templates(kind)
        return Response(_payload(kind, getattr(request, "language", "es")), status=201)


class KindDetailView(KindView):
    @transaction.atomic
    def patch(self, request, kind_id: int):
        self.require(request)
        kind = _get(self.scoped(request), kind_id)
        for field in ("name", "description"):
            if field in request.data:
                setattr(kind, field, (request.data.get(field) or "").strip())
        if "is_active" in request.data:
            kind.is_active = bool(request.data["is_active"])
        kind.save()
        if "components" in request.data:
            _replace_components(kind, request.data["components"])
        if "point_templates" in request.data:
            _replace_templates(kind, request.data["point_templates"])
        return Response(_payload(kind, getattr(request, "language", "es")))

    def delete(self, request, kind_id: int):
        self.require(request)
        kind = _get(self.scoped(request), kind_id)
        if kind.groups.exists():
            raise ValidationError(
                f"El tipo está en uso por {kind.groups.count()} conjuntos; desactívalo"
            )
        if kind.is_builtin:
            raise ValidationError("Un tipo de fábrica no se elimina; desactívalo")
        kind.delete()
        return Response(status=204)


class GroupPointsView(KindView):
    """The actual points of one train, across its equipment."""

    def get(self, request, group_id: int):
        group = _get(AssetGroup.objects.for_company(request.company_id), group_id)
        points = (
            MeasurementPoint.objects.for_company(request.company_id)
            .filter(equipment__asset_group=group)
            .select_related("equipment")
            .order_by("number", "axis")
        )
        return Response({
            "group": {"id": group.id, "name": group.name,
                      "kind": group.kind.code if group.kind else None},
            "equipments": [
                {"id": item.id, "name": item.name, "tag": item.client_tag or item.asset_code,
                 "type": item.equipment_type, "position": item.position_in_group}
                for item in group.equipments.order_by("position_in_group", "id")
            ],
            "points": [
                {
                    "id": point.id, "label": point.label, "number": point.number,
                    "axis": point.axis, "side": point.side, "point_type": point.point_type,
                    "equipment_id": point.equipment_id,
                    "equipment_name": point.equipment.name,
                    "is_active": point.is_active,
                    "reading_count": point.readings.count(),
                }
                for point in points
            ],
        })

    @transaction.atomic
    def post(self, request, group_id: int):
        """Applies the kind's layout to this train's equipment."""
        self.require(request, "assets.manage_point")
        group = _get(
            AssetGroup.objects.for_company(request.company_id).select_related("kind"), group_id
        )
        if group.kind is None:
            raise ValidationError("Este conjunto no tiene tipo asignado")

        templates = list(group.kind.point_templates.select_related("component"))
        if not templates:
            raise ValidationError("El tipo no tiene plantilla de puntos configurada")

        equipments = list(group.equipments.all())
        if not equipments:
            raise ValidationError("El conjunto no tiene equipos todavía")

        # Points 1-2 belong to the first machine of the train, 3-4 to the
        # second, exactly as the report numbers them. Match each component to
        # the equipment that plays its part — by position first, then by type.
        # Ordering equipment alphabetically put "driven" before "driver" and
        # numbered the pump as if it were the motor.
        by_component = {}
        available = list(equipments)
        for index, component in enumerate(group.kind.components.all()):
            match = next(
                (e for e in available if e.position_in_group == component.position),
                None,
            ) or next(
                (e for e in available if e.equipment_type == component.equipment_type),
                None,
            )
            if match is None:
                match = available[0] if available else equipments[min(index, len(equipments) - 1)]
            by_component[component.id] = match
            if match in available and len(available) > 1:
                available.remove(match)

        created = 0
        for template in templates:
            equipment = by_component.get(template.component_id, equipments[0])
            _, made = MeasurementPoint.objects.get_or_create(
                equipment=equipment, number=template.number, axis=template.axis,
                defaults={
                    "company_id": request.company_id,
                    "side": template.side,
                    "point_type": template.point_type,
                },
            )
            created += int(made)
        return Response({"created": created, "total": len(templates)})


def _payload(kind: AssetGroupKind, language: str) -> dict:
    return {
        "id": kind.id,
        "code": kind.code,
        "name": kind.translated("name", language),
        "description": kind.description,
        "is_builtin": kind.is_builtin,
        "is_active": kind.is_active,
        "group_count": kind.groups.count(),
        "components": [
            {"id": c.id, "label": c.label, "equipment_type": c.equipment_type,
             "position": c.position, "order": c.order}
            for c in kind.components.all()
        ],
        "point_templates": [
            {
                "id": t.id, "number": t.number, "axis": t.axis, "label": t.label,
                "side": t.side, "point_type": t.point_type, "magnitudes": t.magnitudes,
                "component_id": t.component_id,
                "component_label": t.component.label if t.component else "",
            }
            for t in kind.point_templates.all()
        ],
    }


def _replace_components(kind: AssetGroupKind, rows) -> None:
    kept = []
    for index, row in enumerate(rows):
        label = (row.get("label") or "").strip()
        if not label:
            continue
        component, _ = AssetGroupComponent.objects.update_or_create(
            kind=kind, label=label,
            defaults={
                "order": index,
                "equipment_type": row.get("equipment_type") or "motor",
                "position": row.get("position") or ("driver" if index == 0 else "driven"),
            },
        )
        kept.append(component.id)
    kind.components.exclude(id__in=kept).delete()


def _replace_templates(kind: AssetGroupKind, rows) -> None:
    components = {c.label: c for c in kind.components.all()}
    prepared = []
    seen = set()
    for order, row in enumerate(rows):
        number = int(row.get("number") or 0)
        axis = row.get("axis") or "H"
        if number < 1:
            raise ValidationError("El número de punto debe ser 1 o mayor")
        if axis not in AXES:
            raise ValidationError(f"Eje desconocido: {axis}")
        if (number, axis) in seen:
            raise ValidationError(f"El punto {number}{axis} está repetido")
        seen.add((number, axis))
        side = row.get("side") or "custom"
        if side not in SIDES:
            raise ValidationError(f"Lado desconocido: {side}")
        prepared.append(
            PointTemplate(
                kind=kind,
                component=components.get(row.get("component_label") or ""),
                number=number,
                axis=axis,
                side=side,
                point_type=row.get("point_type") or "bearing",
                magnitudes=[str(code) for code in (row.get("magnitudes") or [])],
                order=order,
            )
        )
    kind.point_templates.all().delete()
    PointTemplate.objects.bulk_create(prepared)


def _default_templates(kind: AssetGroupKind) -> None:
    axes_magnitudes = {"H": ["vel_rms", "env_accel", "temp"], "V": ["vel_rms"], "A": ["vel_rms"]}
    sides = {0: ("free_end", "coupling_end"), 1: ("coupling_end", "opposite_coupling")}
    rows = []
    for index, component in enumerate(kind.components.all()):
        first = 1 + index * 2
        for offset in (0, 1):
            for axis, magnitudes in axes_magnitudes.items():
                rows.append(
                    PointTemplate(
                        kind=kind, component=component, number=first + offset, axis=axis,
                        side=sides.get(index, ("custom", "custom"))[offset],
                        magnitudes=magnitudes,
                        order=(first + offset) * 10 + list(axes_magnitudes).index(axis),
                    )
                )
    PointTemplate.objects.bulk_create(rows)


def _get(queryset, pk: int):
    row = queryset.filter(id=pk).first()
    if row is None:
        raise ValidationError("No existe")
    return row


def _slug(value: str) -> str:
    cleaned = "".join(c if c.isalnum() else "_" for c in (value or "").strip().lower())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "x"
