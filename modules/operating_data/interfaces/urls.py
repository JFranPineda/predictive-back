from django.urls import path

from modules.operating_data.interfaces.views import (
    ParameterDetailView,
    ParameterListView,
    VisitOperatingView,
)

urlpatterns = [
    path(
        "operating-parameters/",
        ParameterListView.as_view(),
        name="operating-parameters",
    ),
    path(
        "operating-parameters/<int:parameter_id>/",
        ParameterDetailView.as_view(),
        name="operating-parameter-detail",
    ),
    path(
        "service-visits/<int:visit_id>/operating/",
        VisitOperatingView.as_view(),
        name="visit-operating",
    ),
]
