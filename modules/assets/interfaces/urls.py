from django.urls import path
from rest_framework.routers import DefaultRouter

from modules.assets.interfaces.admin_views import (
    AreaCollectionView,
    AreaDetailView,
    AssetGroupCollectionView,
    AssetGroupDetailView,
    EquipmentCollectionView,
    EquipmentDetailView,
    PlantCollectionView,
    PointCollectionView,
    PointDetailView,
    SectorCollectionView,
    SectorDetailView,
)
from modules.assets.interfaces.views import AreaViewSet, EquipmentViewSet

router = DefaultRouter()
router.register("areas", AreaViewSet, basename="area")
router.register("equipments", EquipmentViewSet, basename="equipment")

urlpatterns = [
    path("plants/", PlantCollectionView.as_view(), name="plants"),
    path("areas/new/", AreaCollectionView.as_view(), name="area-create"),
    path("areas/<int:area_id>/edit/", AreaDetailView.as_view(), name="area-detail"),
    path("sectors/", SectorCollectionView.as_view(), name="sector-create"),
    path("sectors/<int:sector_id>/", SectorDetailView.as_view(), name="sector-detail"),
    path("asset-groups/", AssetGroupCollectionView.as_view(), name="asset-groups"),
    path("asset-groups/<int:group_id>/", AssetGroupDetailView.as_view(), name="asset-group-detail"),
    path("equipments/new/", EquipmentCollectionView.as_view(), name="equipment-create"),
    path("equipments/<int:equipment_id>/edit/", EquipmentDetailView.as_view(), name="equipment-edit"),
    path("points/", PointCollectionView.as_view(), name="point-create"),
    path("points/<int:point_id>/", PointDetailView.as_view(), name="point-detail"),
    *router.urls,
]
