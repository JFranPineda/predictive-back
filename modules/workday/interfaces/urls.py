from django.urls import path

from modules.workday.interfaces.views import (
    ObservationCollectionView,
    PermitCollectionView,
    WorkdayCloseView,
    WorkdayDetailView,
    WorkdayListView,
    WorkdayReopenView,
)

urlpatterns = [
    path("workdays/", WorkdayListView.as_view()),
    path("workdays/<int:workday_id>/", WorkdayDetailView.as_view()),
    path("workdays/<int:workday_id>/close/", WorkdayCloseView.as_view()),
    path("workdays/<int:workday_id>/reopen/", WorkdayReopenView.as_view()),
    path("workdays/<int:workday_id>/permits/", PermitCollectionView.as_view()),
    path("workdays/<int:workday_id>/observations/", ObservationCollectionView.as_view()),
]
