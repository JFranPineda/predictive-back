from django.urls import path

from modules.measurements.interfaces.views import TrendView

urlpatterns = [
    path("equipments/<int:equipment_id>/trend/", TrendView.as_view(), name="equipment-trend"),
]
