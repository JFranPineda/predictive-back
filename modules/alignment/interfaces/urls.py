from django.urls import path

from modules.alignment.interfaces.views import (
    AlignmentPhotoView,
    AlignmentRecordDetailView,
    AlignmentRecordListView,
)

urlpatterns = [
    path("alignment-records/", AlignmentRecordListView.as_view()),
    path("alignment-records/<int:record_id>/", AlignmentRecordDetailView.as_view()),
    path("alignment-records/<int:record_id>/photos/", AlignmentPhotoView.as_view()),
]
