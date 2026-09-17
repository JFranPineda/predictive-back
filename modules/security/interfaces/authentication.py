from __future__ import annotations

from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication

from modules.core.domain.i18n import parse_accept_language, resolve_language


class TenantJWTAuthentication(JWTAuthentication):
    """Resolves the company and the language at the exact moment the user
    becomes known.

    Middleware cannot do it: it runs before DRF validates the JWT, so
    `request.user` is still anonymous there and every call ended up with
    `company_id = None` and no permissions. Making it lazy does not work either
    — a `SimpleLazyObject` wrapping an int is rejected by the ORM as a filter
    value. Authentication is the right seam: it is where identity appears.
    """

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None

        user, _token = result
        http_request = request._request
        http_request.company_id = self._company(user, request.headers.get("X-Company-Id"))
        http_request.language = resolve_language(
            requested=request.headers.get("X-Language")
            or parse_accept_language(request.headers.get("Accept-Language")),
            user_preference=user.language or None,
            company_default=self._company_language(http_request.company_id),
        )
        return result

    @staticmethod
    def _company(user, header: str | None) -> int | None:
        from modules.security.application.access import resolve_company

        try:
            return resolve_company(user, header)
        except PermissionError as exc:
            raise PermissionDenied("Company not allowed") from exc

    @staticmethod
    def _company_language(company_id: int | None) -> str | None:
        if not company_id:
            return None
        from modules.core.infrastructure.models import Company

        return (
            Company.objects.filter(id=company_id)
            .values_list("default_language", flat=True)
            .first()
        )
