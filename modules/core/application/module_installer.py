"""Install / uninstall / upgrade use cases.

Django cannot add apps to INSTALLED_APPS at runtime, so every discovered module
is always loaded and migrated; what `install` flips is a DB state that gates
URLs, permissions, menu and event subscriptions. Uninstalling therefore never
destroys history — deleting data is a separate, explicit action.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from modules.core.domain.dependency_graph import DependencyGraph
from modules.core.domain.events import ModuleInstalled, ModuleUninstalled
from modules.core.domain.manifest import Manifest, ModuleInfo
from modules.core.domain.ports import (
    EventPublisher,
    FixtureLoader,
    ManifestSource,
    ModuleStateRepository,
    PermissionSynchronizer,
)


@dataclass(slots=True)
class InstallResult:
    installed: tuple[str, ...]
    already_installed: tuple[str, ...]


class ModuleInstaller:
    def __init__(
        self,
        manifests: ManifestSource,
        states: ModuleStateRepository,
        permissions: PermissionSynchronizer,
        fixtures: FixtureLoader,
        events: EventPublisher,
    ) -> None:
        self._manifests = manifests
        self._states = states
        self._permissions = permissions
        self._fixtures = fixtures
        self._events = events

    def catalog(self) -> tuple[ModuleInfo, ...]:
        states = self._states.all_states()
        installed = self._states.installed_codes()
        infos = []
        for manifest in self._manifests.manifests():
            state, version = states.get(manifest.code, ("uninstalled", None))
            infos.append(
                ModuleInfo(
                    manifest=manifest,
                    state=state,
                    installed_version=version,
                    missing_depends=tuple(d for d in manifest.depends if d not in installed),
                )
            )
        return tuple(sorted(infos, key=lambda i: (i.manifest.category, i.manifest.name)))

    def install(self, code: str) -> InstallResult:
        graph = self._graph()
        installed = self._states.installed_codes()
        order = graph.install_order(code, installed)
        for module_code in order:
            self._activate(graph.get(module_code))
        return InstallResult(
            installed=order,
            already_installed=(code,) if code in installed else (),
        )

    def uninstall(self, code: str) -> None:
        graph = self._graph()
        graph.assert_removable(code, self._states.installed_codes())
        self._permissions.revoke(code)
        self._states.set_state(code, "uninstalled", None)
        self._events.publish(ModuleUninstalled(occurred_at=datetime.now(UTC), module_code=code))

    def upgrade(self, code: str) -> None:
        manifest = self._graph().get(code)
        self._activate(manifest)

    def install_auto_modules(self) -> tuple[str, ...]:
        """Bootstrap: core modules and anything flagged auto_install."""
        done: list[str] = []
        installed = self._states.installed_codes()
        for manifest in self._manifests.manifests():
            if manifest.code in installed:
                continue
            if manifest.is_core or manifest.auto_install:
                done.extend(self.install(manifest.code).installed)
        return tuple(dict.fromkeys(done))

    def _activate(self, manifest: Manifest) -> None:
        self._permissions.sync(manifest)
        self._fixtures.load(manifest)
        self._states.set_state(manifest.code, "installed", manifest.version)
        self._events.publish(
            ModuleInstalled(
                occurred_at=datetime.now(UTC),
                module_code=manifest.code,
                version=manifest.version,
            )
        )

    def _graph(self) -> DependencyGraph:
        return DependencyGraph(self._manifests.manifests())
