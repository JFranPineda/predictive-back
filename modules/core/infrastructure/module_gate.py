"""Whether a module's endpoint answers is decided per request, per tenant.

`/api/v1/` used to be built once, when the process started, from whichever
tenant happened to be in context. Installing a module from /settings/modules
then exposed nothing until every worker restarted, uninstalling left its
endpoints answering, and a second customer's choices were never consulted.

Every module's URLs are now always registered; this middleware answers 404 —
not 403, an uninstalled module stays invisible — for any view whose module
the current tenant has not installed.
"""

from __future__ import annotations

from functools import cache

from django.http import JsonResponse


def module_of(view_func) -> str | None:
    """`modules.<code>.…` of the view behind a URL, or None for a view that is
    not a module's (login, the schema, the admin)."""
    view_class = getattr(view_func, "view_class", None) or getattr(view_func, "cls", None)
    dotted = (view_class or view_func).__module__
    parts = dotted.split(".")
    return parts[1] if len(parts) > 2 and parts[0] == "modules" else None


@cache
def _always_on() -> frozenset[str]:
    from modules.core.infrastructure.discovery import discover_manifests

    return frozenset(manifest.code for manifest in discover_manifests() if manifest.is_core)


class ModuleGateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        code = module_of(view_func)
        if code is None or code in _always_on():
            return None
        from modules.core.infrastructure.routing import installed_codes

        if code in installed_codes():
            return None
        return JsonResponse(
            {"type": "not_found", "status": 404, "detail": f"El módulo '{code}' no está instalado"},
            status=404,
        )
