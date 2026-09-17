from django.urls import path

from modules.media.interfaces.views import MediaCollectionView, MediaDetailView

urlpatterns = [
    path("media/", MediaCollectionView.as_view(), name="media"),
    path("media/<int:media_id>/", MediaDetailView.as_view(), name="media-detail"),
]
