from django.urls import path

from modules.diagnostics.interfaces.views import FaultModeListView, VisitFaultsView

urlpatterns = [
    path("fault-modes/", FaultModeListView.as_view(), name="fault-modes"),
    path("service-visits/<int:visit_id>/faults/", VisitFaultsView.as_view(), name="visit-faults"),
]
