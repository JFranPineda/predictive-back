from __future__ import annotations

from django.db.models import Count
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from modules.assets.interfaces.serializers import (
    AreaSerializer,
    EquipmentSerializer,
    MeasurementPointSerializer,
)
from modules.assets.models import Area, Equipment, MeasurementPoint


class TenantViewSet(viewsets.ReadOnlyModelViewSet):
    """Every queryset is scoped to the company on the request, and narrowed
    again by the areas the user may reach. An external inspector restricted to
    two areas cannot page his way into the rest of the plant."""

    class pagination_class(PageNumberPagination):
        page_size_query_param = "page_size"
        max_page_size = 200

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "language": getattr(self.request, "language", "es")}

    def allowed_areas(self):
        from modules.security.application.access import allowed_area_ids

        return allowed_area_ids(self.request.user, self.request.company_id)


class AreaViewSet(TenantViewSet):
    serializer_class = AreaSerializer

    def get_queryset(self):
        queryset = (
            Area.objects.for_company(self.request.company_id)
            .annotate(equipment_count=Count("sectors__groups__equipments"))
            .prefetch_related("sectors")
            .order_by("code")
        )
        areas = self.allowed_areas()
        return queryset if areas is None else queryset.filter(id__in=areas)


class EquipmentViewSet(TenantViewSet):
    serializer_class = EquipmentSerializer

    def get_queryset(self):
        queryset = (
            Equipment.objects.for_company(self.request.company_id)
            .select_related(
                "asset_group__sector__area", "asset_group__kind",
                "condition_status", "availability_status",
            )
            .order_by("asset_group__sector__area__code", "client_tag", "asset_code")
        )
        areas = self.allowed_areas()
        if areas is not None:
            queryset = queryset.filter(asset_group__sector__area_id__in=areas)

        params = self.request.query_params
        if params.get("area"):
            queryset = queryset.filter(asset_group__sector__area_id=params["area"])
        if params.get("status"):
            queryset = queryset.filter(condition_status__code=params["status"])
        if params.get("search"):
            search = params["search"]
            queryset = queryset.filter(name__icontains=search) | queryset.filter(
                client_tag__icontains=search
            )
        return queryset

    @action(detail=True, methods=["get"])
    def points(self, request, pk=None):
        points = MeasurementPoint.objects.filter(
            equipment_id=pk, company_id=request.company_id
        ).order_by("number", "axis")
        return Response(MeasurementPointSerializer(points, many=True).data)
