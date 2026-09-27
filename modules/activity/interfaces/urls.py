from django.urls import path

from modules.activity.interfaces.views import (
    ActivityActorsView,
    ActivityEventsView,
    ActivityExportView,
    ActivityListView,
)

urlpatterns = [
    path("activity/", ActivityListView.as_view()),
    path("activity/actors/", ActivityActorsView.as_view()),
    path("activity/events/", ActivityEventsView.as_view()),
    path("activity/export/", ActivityExportView.as_view()),
]
