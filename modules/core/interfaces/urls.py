from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from modules.core.interfaces.history_views import HistoryFileView, HistoryView
from modules.core.interfaces.views import BootstrapView, ModuleViewSet

router = DefaultRouter()
router.register("modules", ModuleViewSet, basename="module")

urlpatterns = [
    path("session/bootstrap/", BootstrapView.as_view(), name="bootstrap"),
    path("history/", HistoryView.as_view(), name="history"),
    path("history/<slug:source>/<str:period>/", HistoryFileView.as_view(), name="history-file"),
    *router.urls,
]
