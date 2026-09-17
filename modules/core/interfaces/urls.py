from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from modules.core.interfaces.views import BootstrapView, ModuleViewSet

router = DefaultRouter()
router.register("modules", ModuleViewSet, basename="module")

urlpatterns = [
    path("session/bootstrap/", BootstrapView.as_view(), name="bootstrap"),
    *router.urls,
]
