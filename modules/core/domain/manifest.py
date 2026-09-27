"""Module manifest — the contract every module declares about itself.

Pure python on purpose: the frontend reads the same shape over HTTP, and the
installer reasons about dependencies without touching the ORM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ModuleState = Literal["uninstalled", "installed", "to_upgrade", "broken"]


@dataclass(frozen=True, slots=True)
class MenuItem:
    label: str
    route: str
    icon: str = "square"
    order: int = 100
    parent: str | None = None
    permission: str | None = None


@dataclass(frozen=True, slots=True)
class Manifest:
    code: str
    name: str
    version: str
    summary: str = ""
    category: str = "Otros"
    depends: tuple[str, ...] = ()
    is_core: bool = False
    auto_install: bool = False
    permissions: tuple[tuple[str, str], ...] = ()
    menu: tuple[MenuItem, ...] = ()
    fixtures: tuple[str, ...] = ()
    settings_schema: str | None = None
    on_install: str | None = None
    on_uninstall: str | None = None
    on_upgrade: str | None = None
    # Dotted path to `guard(request, view_func, view_kwargs)`, asked before
    # every write of the tenants that installed the module. A rule that spans
    # other modules' data (Fase 3's day close) lives here, not in each view.
    write_guard: str | None = None
    # Dotted path to `observe(request, response, view_func, view_kwargs)`,
    # told about every request once it has been answered — what the activity
    # log listens with. It can never change the response.
    request_observer: str | None = None
    events_subscribed: tuple[str, ...] = ()
    events_published: tuple[str, ...] = ()
    provides_techniques: tuple[str, ...] = ()

    @property
    def app_label(self) -> str:
        return self.code


@dataclass(slots=True)
class ModuleInfo:
    """A manifest plus its runtime state. What the API returns."""

    manifest: Manifest
    state: ModuleState = "uninstalled"
    installed_version: str | None = None
    missing_depends: tuple[str, ...] = field(default_factory=tuple)

    @property
    def upgradable(self) -> bool:
        return self.state == "installed" and self.installed_version != self.manifest.version
