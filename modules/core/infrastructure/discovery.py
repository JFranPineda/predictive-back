"""Finds every `modules/<name>/manifest.py` and exposes their MANIFEST."""

from __future__ import annotations

import importlib
import pkgutil
from functools import lru_cache

import modules
from modules.core.domain.manifest import Manifest


@lru_cache(maxsize=1)
def discover_manifests() -> tuple[Manifest, ...]:
    found: list[Manifest] = []
    for info in pkgutil.iter_modules(modules.__path__):
        if not info.ispkg:
            continue
        try:
            module = importlib.import_module(f"modules.{info.name}.manifest")
        except ModuleNotFoundError:
            continue
        manifest = getattr(module, "MANIFEST", None)
        if isinstance(manifest, Manifest):
            found.append(manifest)
    return tuple(sorted(found, key=lambda m: m.code))


class DjangoManifestSource:
    def manifests(self) -> tuple[Manifest, ...]:
        return discover_manifests()


def module_app_labels() -> list[str]:
    """What settings.INSTALLED_APPS gets. Every module is always loaded;
    activation is data, not import state."""
    return [f"modules.{m.code}" for m in discover_manifests()]
