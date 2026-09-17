"""Builds `/api/v1/` from the modules that are actually installed.

A module that is not installed contributes no URL at all — a 404, not a 403,
because an uninstalled module should be invisible.
"""

from __future__ import annotations

import importlib

from django.urls import include, path

from modules.core.infrastructure.discovery import discover_manifests


def installed_codes() -> frozenset[str]:
    from django.db import DatabaseError
    from django.utils.connection import ConnectionDoesNotExist

    from modules.core.infrastructure.repositories import DjangoModuleStateRepository
    from modules.licensing.infrastructure.context import TenantNotResolved

    try:
        return DjangoModuleStateRepository().installed_codes()
    except (DatabaseError, ConnectionDoesNotExist, TenantNotResolved):
        # First boot, or a process with no tenant in context: serve the core
        # modules so the system can be migrated and a tenant registered.
        return frozenset(m.code for m in discover_manifests() if m.is_core)


def module_urlpatterns() -> list:
    active = installed_codes()
    patterns = []
    for manifest in discover_manifests():
        if manifest.code not in active and not manifest.is_core:
            continue
        try:
            urls = importlib.import_module(f"modules.{manifest.code}.interfaces.urls")
        except ModuleNotFoundError:
            continue
        patterns.append(path("", include(urls)))
    return patterns
