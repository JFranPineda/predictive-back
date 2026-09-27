"""Why a subject's data cannot be edited right now, as the screens ask it.

The read-side twin of `write_guard`: a module that refuses writes (the
workday) also names a lock in its manifest, so a visit or a train shows its
fields locked with the reason instead of failing on save. Only the locks of
the modules the tenant has installed are asked.
"""

from __future__ import annotations

import importlib
from functools import cache


@cache
def _locks() -> tuple[tuple[str, object], ...]:
    from modules.core.infrastructure.discovery import discover_manifests

    found = []
    for manifest in discover_manifests():
        if not manifest.edit_lock:
            continue
        module_path, _, name = manifest.edit_lock.rpartition(".")
        found.append((manifest.code, getattr(importlib.import_module(module_path), name)))
    return tuple(found)


def edit_lock(request, **subject) -> str | None:
    """The first installed module's reason to keep this subject read-only."""
    if not _locks():
        return None
    from modules.core.infrastructure.routing import installed_codes

    installed = installed_codes()
    for code, lock in _locks():
        if code not in installed:
            continue
        reason = lock(request.user, request.company_id, subject)
        if reason:
            return reason
    return None
