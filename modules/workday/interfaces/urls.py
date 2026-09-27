from django.urls import path

from modules.workday.interfaces.job_views import (
    JobCloseView,
    JobCollectionView,
    JobCrewView,
    JobDetailView,
    JobSignView,
    JobUnlockView,
)
from modules.workday.interfaces.views import (
    ObservationCollectionView,
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
    path("workdays/<int:workday_id>/jobs/", JobCollectionView.as_view()),
    path("workdays/<int:workday_id>/observations/", ObservationCollectionView.as_view()),
    path("workday-jobs/<int:job_id>/", JobDetailView.as_view()),
    path("workday-jobs/<int:job_id>/crew/", JobCrewView.as_view()),
    path("workday-jobs/<int:job_id>/crew/<int:signature_id>/", JobCrewView.as_view()),
    path("workday-jobs/<int:job_id>/sign/", JobSignView.as_view()),
    path("workday-jobs/<int:job_id>/unlock/", JobUnlockView.as_view()),
    path("workday-jobs/<int:job_id>/close/", JobCloseView.as_view()),
]
