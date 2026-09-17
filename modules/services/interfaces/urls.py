from django.urls import path

from modules.services.interfaces.views import AuthorshipView, ServiceOrderListView
from modules.services.interfaces.visit_views import (
    VisitDetailView,
    VisitEntriesView,
    VisitReadingsView,
)

urlpatterns = [
    path("service-orders/", ServiceOrderListView.as_view(), name="service-orders"),
    path("service-visits/authorship/", AuthorshipView.as_view(), name="visit-authorship"),
    path("service-visits/<int:visit_id>/", VisitDetailView.as_view(), name="visit-detail"),
    path("service-visits/<int:visit_id>/readings/", VisitReadingsView.as_view(), name="visit-readings"),
    path("service-visits/<int:visit_id>/entries/", VisitEntriesView.as_view(), name="visit-entries"),
]
