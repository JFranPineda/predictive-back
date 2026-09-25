from django.urls import path

from modules.licensing.interfaces.usage_views import LicenseUsageView
from modules.licensing.interfaces.views import LicenseStatusView

urlpatterns = [
    path("license/status/", LicenseStatusView.as_view(), name="license-status"),
    path("license/usage/", LicenseUsageView.as_view(), name="license-usage"),
]
