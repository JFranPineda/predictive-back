"""Two gates, in this order: which customer, then may they work today.

Both run before authentication, because "who is the user" is a question you
can only ask once you know which database to look in.
"""

from __future__ import annotations

import re

from django.conf import settings
from django.http import JsonResponse

from modules.licensing.application.license_service import current_verdict
from modules.licensing.application.tenant_resolver import UnknownTenant, resolve, tenant_from_host
from modules.licensing.domain.license import Access
from modules.licensing.infrastructure.context import set_current_tenant
from modules.licensing.infrastructure.keys import trusted_keys

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

# Once the subscription lapses (v4 Phase 4) the customer still reads and
# exports, and no longer records work or issues reports. Both lists are
# declared once, here, short enough to review: a report misfiled as data would
# let work go on unpaid, an export left out would hold the customer's data.
# The full export lives under /api/v1/license/ and is exempt altogether.
EXPORT_PATHS = (
    re.compile(r"^/api/v1/activity/export/$"),
    re.compile(r"^/api/v1/asset-groups/\d+/matrix/export/$"),
    re.compile(r"^/api/v1/history/"),
)
WORK_REPORT_PATHS = (
    re.compile(r"^/api/v1/reports/(mpd|end|monthly|corrective)/$"),
    re.compile(r"^/api/v1/ut-rollers/orders/\d+/groups/\d+/report/$"),
)


def classify(method: str, path: str) -> Access:
    """Changing data is writing whatever the path; a report is the deliverable
    we charge for; everything else read is data, the customer's."""
    if method not in SAFE_METHODS:
        return Access.WRITE
    if any(pattern.match(path) for pattern in WORK_REPORT_PATHS):
        return Access.REPORT
    if any(pattern.match(path) for pattern in EXPORT_PATHS):
        return Access.EXPORT
    return Access.READ


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
    """Expiry degrades in steps, and never as far as the customer's data:
    read-only during the grace period; after it, reading and exporting only.
    A crew mid-round does not lose its work over an invoice."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant = getattr(request, "tenant", None)
        if tenant is None or request.path.startswith(LICENSE_EXEMPT_PREFIXES):
            return self.get_response(request)

        verdict = current_verdict(
            tenant.code,
            keys=trusted_keys(),
            suspended=tenant.is_suspended,
        )
        request.license = verdict

        access = classify(request.method, request.path)
        if not verdict.allows(access):
            code = "license_report_blocked" if access is Access.REPORT else "license_read_only"
            response = _problem(code, verdict.reason or "Licencia no vigente", 402)
        else:
            response = self.get_response(request)
        # On refusals too: the UI explains the state instead of a blank screen.
        response["X-License-Status"] = verdict.status.value
        response["X-License-Days-Left"] = str(verdict.days_left)
        return response


def _problem(code: str, title: str, status: int) -> JsonResponse:
    return JsonResponse({"type": code, "title": title, "status": status}, status=status)
