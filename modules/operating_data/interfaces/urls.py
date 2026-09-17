from django.urls import path

from modules.operating_data.interfaces.views import ParameterListView, VisitOperatingView

urlpatterns = [
    path("operating-parameters/", ParameterListView.as_view(), name="operating-parameters"),
    path(
        "service-visits/<int:visit_id>/operating/",
        VisitOperatingView.as_view(),
        name="visit-operating",
    ),
]
