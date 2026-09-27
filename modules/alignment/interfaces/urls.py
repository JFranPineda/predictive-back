from django.urls import path

from modules.alignment.interfaces.views import (
    AlignmentPhotoView,
    AlignmentRecordDetailView,
    AlignmentRecordListView,
    AlignmentScaleView,
)

urlpatterns = [
    path("alignment-records/", AlignmentRecordListView.as_view()),
    path("alignment-records/<int:record_id>/", AlignmentRecordDetailView.as_view()),
    path("alignment-records/<int:record_id>/photos/", AlignmentPhotoView.as_view()),
    path("alignment-records/<int:record_id>/photos/<int:photo_id>/", AlignmentPhotoView.as_view()),
    path("alignment-scales/<int:standard_id>/", AlignmentScaleView.as_view()),
]
