from django.urls import path

from modules.diagnostics.interfaces.views import (
    FaultModeDetailView,
    FaultModeListView,
    VisitFaultsView,
)

urlpatterns = [
    path("fault-modes/", FaultModeListView.as_view(), name="fault-modes"),
    path(
        "fault-modes/<int:fault_id>/",
        FaultModeDetailView.as_view(),
        name="fault-mode-detail",
    ),
    path("service-visits/<int:visit_id>/faults/", VisitFaultsView.as_view(), name="visit-faults"),
]
