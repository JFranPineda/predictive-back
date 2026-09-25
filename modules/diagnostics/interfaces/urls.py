from django.urls import path

from modules.diagnostics.interfaces.views import (
    FaultModeDetailView,
    FaultModeListView,
    OtherFaultsView,
    VisitFaultsView,
)

urlpatterns = [
    path("fault-modes/", FaultModeListView.as_view(), name="fault-modes"),
    path("fault-modes/others/", OtherFaultsView.as_view(), name="fault-mode-others"),
    path(
        "fault-modes/<int:fault_id>/",
        FaultModeDetailView.as_view(),
        name="fault-mode-detail",
    ),
    path("service-visits/<int:visit_id>/faults/", VisitFaultsView.as_view(), name="visit-faults"),
]
