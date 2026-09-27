from django.urls import path

from modules.ut_rollers.interfaces.journal_views import (
    GroupReportImageView,
    GroupReportView,
    JournalSheetView,
    ResultsSummaryView,
)
from modules.ut_rollers.interfaces.views import (
    IndicationDetailView,
    IndicationListView,
    RollerCreateView,
    RollerGroupsView,
    RollerSheetView,
)

urlpatterns = [
    path("ut-rollers/groups/", RollerGroupsView.as_view()),
    path("ut-rollers/groups/<int:group_id>/rollers/", RollerCreateView.as_view()),
    path("ut-rollers/orders/<int:order_id>/sheet/", RollerSheetView.as_view()),
    path("ut-rollers/orders/<int:order_id>/journals/", JournalSheetView.as_view()),
    path("ut-rollers/orders/<int:order_id>/results/", ResultsSummaryView.as_view()),
    path("ut-rollers/orders/<int:order_id>/groups/<int:group_id>/report/", GroupReportView.as_view()),
    path(
        "ut-rollers/orders/<int:order_id>/groups/<int:group_id>/report/images/",
        GroupReportImageView.as_view(),
    ),
    path(
        "ut-rollers/orders/<int:order_id>/groups/<int:group_id>/report/images/<int:asset_id>/",
        GroupReportImageView.as_view(),
    ),
    path("ut-rollers/indications/", IndicationListView.as_view()),
    path("ut-rollers/indications/<int:indication_id>/", IndicationDetailView.as_view()),
]
