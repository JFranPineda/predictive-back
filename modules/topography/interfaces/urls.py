from django.urls import path

from modules.topography.interfaces.views import (
    TopographyElementDetailView,
    TopographyElementListView,
    TopographyHistoryView,
)

urlpatterns = [
    path("topography-elements/", TopographyElementListView.as_view()),
    path("topography-elements/history/", TopographyHistoryView.as_view()),
    path("topography-elements/<int:reading_id>/", TopographyElementDetailView.as_view()),
]
