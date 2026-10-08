from django.urls import path

from modules.thresholds.interfaces.admin_views import (
    StandardCollectionView,
    StandardDetailView,
    StatusCollectionView,
    ThresholdSetCollectionView,
    ThresholdSetDetailView,
)
from modules.thresholds.interfaces.profile_views import StatusProfileDetailView, StatusProfileListView
from modules.thresholds.interfaces.views import (
    StandardListView,
    StatusDetailView,
    StatusListView,
    ThresholdSetListView,
)

urlpatterns = [
    path("statuses/", StatusListView.as_view(), name="statuses"),
    path("status-profiles/", StatusProfileListView.as_view(), name="status-profiles"),
    path("status-profiles/<slug:technique_code>/", StatusProfileDetailView.as_view(), name="status-profile"),
    path("statuses/new/", StatusCollectionView.as_view(), name="status-create"),
    path("statuses/<int:status_id>/", StatusDetailView.as_view(), name="status-detail"),
    path("standards/", StandardListView.as_view(), name="standards"),
    path("standards/new/", StandardCollectionView.as_view(), name="standard-create"),
    path("standards/<int:standard_id>/", StandardDetailView.as_view(), name="standard-detail"),
    path("threshold-sets/", ThresholdSetListView.as_view(), name="threshold-sets"),
    path("threshold-sets/new/", ThresholdSetCollectionView.as_view(), name="threshold-set-create"),
    path("threshold-sets/<int:set_id>/", ThresholdSetDetailView.as_view(), name="threshold-set-detail"),
]
