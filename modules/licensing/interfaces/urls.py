from django.urls import path

from modules.licensing.interfaces.views import LicenseStatusView

urlpatterns = [path("license/status/", LicenseStatusView.as_view(), name="license-status")]
