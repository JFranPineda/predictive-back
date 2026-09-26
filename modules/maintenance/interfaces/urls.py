from django.urls import path

from modules.maintenance.interfaces.views import (
    WorkRecordDetailView,
    WorkRecordListView,
    WorkRecordMarkersView,
)

urlpatterns = [
    path("work-records/", WorkRecordListView.as_view()),
    path("work-records/markers/", WorkRecordMarkersView.as_view()),
    path("work-records/<int:record_id>/", WorkRecordDetailView.as_view()),
]
