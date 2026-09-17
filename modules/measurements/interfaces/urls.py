from django.urls import path

from modules.measurements.interfaces.catalogue_views import (
    MagnitudeListView,
    TechniqueListView,
    UnitListView,
)
from modules.measurements.interfaces.views import TrendView

urlpatterns = [
    path("equipments/<int:equipment_id>/trend/", TrendView.as_view(), name="equipment-trend"),
    path("techniques/", TechniqueListView.as_view(), name="techniques"),
    path("units/", UnitListView.as_view(), name="units"),
    path("magnitudes/", MagnitudeListView.as_view(), name="magnitudes"),
]
