from django.urls import path

from modules.measurements.interfaces.catalogue_views import (
    MagnitudeListView,
    TechniqueListView,
    UnitListView,
)
from modules.measurements.interfaces.matrix_views import EquipmentMatrixView
from modules.measurements.interfaces.views import TrendView

urlpatterns = [
    path("equipments/<int:equipment_id>/trend/", TrendView.as_view(), name="equipment-trend"),
    path(
        "equipments/<int:equipment_id>/matrix/",
        EquipmentMatrixView.as_view(),
        name="equipment-matrix",
    ),
    path("techniques/", TechniqueListView.as_view(), name="techniques"),
    path("units/", UnitListView.as_view(), name="units"),
    path("magnitudes/", MagnitudeListView.as_view(), name="magnitudes"),
]
