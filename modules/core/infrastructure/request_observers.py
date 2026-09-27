"""Requests a module may watch, whichever module answered them.

The twin of `write_guard`: a module names an observer in its manifest and
this middleware tells the observers of the modules the current tenant has
installed about every answered request. Uninstall the module and nobody is
listening any more.

An observer that fails is logged and ignored: watching a request must never
be the reason it fails.
"""

from __future__ import annotations

import importlib
import logging
from functools import cache

logger = logging.getLogger(__name__)

# JSON bodies up to this size are read before the view, so an observer can
# still see which fields a write carried after DRF has consumed the stream.
BODY_PEEK_LIMIT = 256 * 1024


@cache
def _observers() -> tuple[tuple[str, object], ...]:
    from modules.core.infrastructure.discovery import discover_manifests

    found = []
    for manifest in discover_manifests():
        if not manifest.request_observer:
            continue
        module_path, _, name = manifest.request_observer.rpartition(".")
        found.append((manifest.code, getattr(importlib.import_module(module_path), name)))
    return tuple(found)


class RequestObserverMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not _observers():
            return response
        from modules.core.infrastructure.routing import installed_codes

        try:
            installed = installed_codes()
        except Exception:  # no tenant resolved: nothing to observe with
            return response
        view_func, view_kwargs = getattr(request, "_observed_view", (None, {}))
        for code, observe in _observers():
            if code not in installed:
                continue
            try:
                observe(request, response, view_func, view_kwargs)
            except Exception:
                logger.exception("request observer of %s failed", code)
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        request._observed_view = (view_func, view_kwargs)
        if (
            _observers()
            and request.content_type == "application/json"
            and int(request.META.get("CONTENT_LENGTH") or 0) <= BODY_PEEK_LIMIT
        ):
            # Cached on the request: DRF reads the same bytes afterwards.
            _ = request.body
        return None
