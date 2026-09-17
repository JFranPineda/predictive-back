from __future__ import annotations

from modules.core.domain.i18n import parse_accept_language, resolve_language


class RequestContextMiddleware:
    """Sets the safe defaults for tenant company and language.

    The real values are filled in by `TenantJWTAuthentication`, because they
    depend on who the user is and DRF only knows that after this middleware has
    run. Anything reached without a token — the licence status endpoint, the
    schema — works with these defaults.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.company_id = None
        request.language = resolve_language(
            requested=request.headers.get("X-Language")
            or parse_accept_language(request.headers.get("Accept-Language"))
        )
        response = self.get_response(request)
        response["Content-Language"] = str(getattr(request, "language", "es"))
        return response
