from django.urls import path

from modules.media.interfaces.views import (
    EquipmentMediaView,
    MediaCollectionView,
    MediaDetailView,
)

urlpatterns = [
    path("media/", MediaCollectionView.as_view(), name="media"),
    path(
        "media/equipment/<int:equipment_id>/",
        EquipmentMediaView.as_view(),
        name="media-by-equipment",
    ),
    path("media/<int:media_id>/", MediaDetailView.as_view(), name="media-detail"),
]
