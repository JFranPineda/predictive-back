from django.urls import path

from modules.topography.interfaces.views import (
    TopographyBoxPhotoView,
    TopographyElementDetailView,
    TopographyElementListView,
    TopographyHistoryView,
    TopographySurveyImageView,
    TopographySurveyView,
)

urlpatterns = [
    path("topography-visits/<int:visit_id>/survey/", TopographySurveyView.as_view()),
    path("topography-visits/<int:visit_id>/survey/images/", TopographySurveyImageView.as_view()),
    path("topography-visits/<int:visit_id>/survey/images/<str:role>/", TopographySurveyImageView.as_view()),
    path("topography-elements/", TopographyElementListView.as_view()),
    path("topography-elements/history/", TopographyHistoryView.as_view()),
    path("topography-elements/<int:reading_id>/", TopographyElementDetailView.as_view()),
    path("topography-elements/<int:reading_id>/photos/", TopographyBoxPhotoView.as_view()),
    path("topography-elements/<int:reading_id>/photos/<str:box>/", TopographyBoxPhotoView.as_view()),
]
