from django.urls import path

from modules.thresholds.interfaces.views import (
    StandardListView,
    StatusDetailView,
    StatusListView,
    ThresholdSetListView,
)

urlpatterns = [
    path("statuses/", StatusListView.as_view(), name="statuses"),
    path("statuses/<int:status_id>/", StatusDetailView.as_view(), name="status-detail"),
    path("standards/", StandardListView.as_view(), name="standards"),
    path("threshold-sets/", ThresholdSetListView.as_view(), name="threshold-sets"),
]
