"""Two gates, in this order: which customer, then may they work today.

Both run before authentication, because "who is the user" is a question you
can only ask once you know which database to look in.
"""

from __future__ import annotations

from django.conf import settings
from django.http import JsonResponse

from modules.licensing.application.license_service import current_verdict
from modules.licensing.application.tenant_resolver import UnknownTenant, resolve, tenant_from_host
from modules.licensing.infrastructure.context import set_current_tenant

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Paths that must answer even when the licence blocks, or the UI cannot explain
# why it is locked and the customer sees a blank screen.
LICENSE_EXEMPT_PREFIXES = (
    "/api/v1/auth/",
    "/api/v1/license/",
    "/api/schema",
    "/api/docs",
    "/admin/",
)


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        code = (
            request.headers.get("X-Tenant")
            or tenant_from_host(request.get_host(), getattr(settings, "BASE_DOMAIN", ""))
            or getattr(settings, "DEFAULT_TENANT", None)
        )
        if not code:
            return _problem("tenant_required", "No se pudo determinar el cliente", 400)

        set_current_tenant(code)
        try:
            request.tenant = resolve(code)
        except UnknownTenant:
            set_current_tenant(None)
            return _problem("unknown_tenant", f"Cliente '{code}' no registrado", 404)

        try:
            return self.get_response(request)
        finally:
            set_current_tenant(None)


class LicenseMiddleware:
    """Expiry degrades before it blocks: read-only first, refusal after the
    grace period. A crew mid-round does not lose its work over an invoice."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant = getattr(request, "tenant", None)
        if tenant is None or request.path.startswith(LICENSE_EXEMPT_PREFIXES):
            return self.get_response(request)

        verdict = current_verdict(
            tenant.code,
            secret=settings.LICENSE_SECRET,
            suspended=tenant.is_suspended,
        )
        request.license = verdict

        if verdict.blocks:
            return _problem("license_blocked", verdict.reason or "Licencia no vigente", 402)
        if verdict.read_only and request.method not in SAFE_METHODS:
            return _problem("license_read_only", verdict.reason, 402)

        response = self.get_response(request)
        response["X-License-Status"] = verdict.status.value
        response["X-License-Days-Left"] = str(verdict.days_left)
        return response


def _problem(code: str, title: str, status: int) -> JsonResponse:
    return JsonResponse({"type": code, "title": title, "status": status}, status=status)
