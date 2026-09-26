"""Writes a module may veto, whichever module owns the endpoint.

A rule like "once the day is closed, technicians change nothing" spans every
module's data. Writing it into each view would make every module know about
the one that imposes it; instead that module names a guard in its manifest,
and this middleware asks the guards of the modules the current tenant has
installed. Uninstall the module and its rule is gone with it.
"""

from __future__ import annotations

import importlib
from functools import cache

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@cache
def _guards() -> tuple[tuple[str, object], ...]:
    from modules.core.infrastructure.discovery import discover_manifests

    found = []
    for manifest in discover_manifests():
        if not manifest.write_guard:
            continue
        module_path, _, name = manifest.write_guard.rpartition(".")
        found.append((manifest.code, getattr(importlib.import_module(module_path), name)))
    return tuple(found)


class WriteGuardMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.method in SAFE_METHODS or not _guards():
            return None
        from modules.core.infrastructure.routing import installed_codes

        installed = installed_codes()
        for code, guard in _guards():
            if code not in installed:
                continue
            verdict = guard(request, view_func, view_kwargs)
            if verdict is not None:
                return verdict
        return None
