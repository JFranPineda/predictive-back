from django.urls import path

from modules.nameplate.interfaces.views import NameplateView

urlpatterns = [
    path("equipments/<int:equipment_id>/nameplate/", NameplateView.as_view(), name="nameplate"),
]
