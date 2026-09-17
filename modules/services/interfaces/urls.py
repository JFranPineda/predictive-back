from django.urls import path

from modules.services.interfaces.admin_views import (
    LogEntryDetailView,
    ServiceOrderAdminView,
    ServiceOrderDetailView,
    VisitAdminView,
    VisitCollectionView,
    VisitParticipantView,
)
from modules.services.interfaces.views import AuthorshipView, ServiceOrderListView
from modules.services.interfaces.visit_views import (
    VisitDetailView,
    VisitEntriesView,
    VisitReadingsView,
)

urlpatterns = [
    path("service-orders/", ServiceOrderListView.as_view(), name="service-orders"),
    path("service-orders/new/", ServiceOrderAdminView.as_view(), name="service-order-create"),
    path("service-orders/<int:order_id>/", ServiceOrderDetailView.as_view(), name="service-order-detail"),
    path("service-visits/", VisitCollectionView.as_view(), name="visit-create"),
    path("service-visits/authorship/", AuthorshipView.as_view(), name="visit-authorship"),
    path("service-visits/<int:visit_id>/", VisitDetailView.as_view(), name="visit-detail"),
    path("service-visits/<int:visit_id>/edit/", VisitAdminView.as_view(), name="visit-edit"),
    path("service-visits/<int:visit_id>/participants/", VisitParticipantView.as_view(), name="visit-participants"),
    path("service-visits/<int:visit_id>/readings/", VisitReadingsView.as_view(), name="visit-readings"),
    path("service-visits/<int:visit_id>/entries/", VisitEntriesView.as_view(), name="visit-entries"),
    path("log-entries/<int:entry_id>/", LogEntryDetailView.as_view(), name="log-entry-detail"),
]
