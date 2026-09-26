from django.urls import path

from modules.reports.interfaces.views import (
    CorrectiveReportView,
    EndReportView,
    MonthlyReportView,
    MpdReportView,
    ReportOrdersView,
)

urlpatterns = [
    path("reports/mpd/", MpdReportView.as_view()),
    path("reports/end/", EndReportView.as_view()),
    path("reports/monthly/", MonthlyReportView.as_view()),
    path("reports/corrective/", CorrectiveReportView.as_view()),
    path("reports/orders/", ReportOrdersView.as_view()),
]
