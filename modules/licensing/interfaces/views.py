from __future__ import annotations

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.licensing.application.license_service import current_verdict, latest_record
from modules.licensing.infrastructure.keys import trusted_keys


class LicenseStatusView(APIView):
    """Reachable even when the licence blocks, so the UI can say why instead of
    showing an empty screen."""

    permission_classes = [AllowAny]

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if tenant is None:
            return Response({"status": "unknown"}, status=400)
        record = latest_record(tenant.code)
        verdict = current_verdict(
            tenant.code, keys=trusted_keys(), suspended=tenant.is_suspended
        )
        return Response(
            {
                "tenant": tenant.code,
                "tenant_name": tenant.name,
                "deployment": tenant.deployment,
                "status": verdict.status.value,
                "read_only": verdict.read_only,
                "days_left": verdict.days_left,
                "reason": verdict.reason,
                "should_warn": verdict.should_warn,
                # Lapsed: reading and exporting only (v4 Phase 4).
                "lapsed": verdict.lapsed,
                "valid_until": record.valid_until.isoformat() if record else None,
                # On-premise renews by file or online (v4 Phase 3); hosted we renew ourselves.
                "renewable": tenant.deployment == "on_premise",
            }
        )
