from django.urls import path

from modules.licensing.interfaces.renewal_views import LicenseRenewalRequestView, LicenseRenewView
from modules.licensing.interfaces.usage_views import LicenseUsageView
from modules.licensing.interfaces.views import LicenseStatusView

urlpatterns = [
    path("license/status/", LicenseStatusView.as_view(), name="license-status"),
    path("license/usage/", LicenseUsageView.as_view(), name="license-usage"),
    path("license/renewal/request/", LicenseRenewalRequestView.as_view(), name="license-renewal-request"),
    path("license/renew/", LicenseRenewView.as_view(), name="license-renew"),
]
