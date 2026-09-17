from __future__ import annotations

from typing import Protocol, runtime_checkable

from .events import DomainEvent
from .manifest import Manifest, ModuleInfo, ModuleState


@runtime_checkable
class ModuleStateRepository(Protocol):
    def all_states(self) -> dict[str, tuple[ModuleState, str | None]]: ...

    def installed_codes(self) -> frozenset[str]: ...

    def set_state(self, code: str, state: ModuleState, version: str | None) -> None: ...


@runtime_checkable
class ManifestSource(Protocol):
    def manifests(self) -> tuple[Manifest, ...]: ...


@runtime_checkable
class EventPublisher(Protocol):
    def publish(self, event: DomainEvent) -> None: ...


@runtime_checkable
class PermissionSynchronizer(Protocol):
    def sync(self, module: Manifest) -> None: ...

    def revoke(self, module_code: str) -> None: ...


@runtime_checkable
class FixtureLoader(Protocol):
    def load(self, module: Manifest) -> None: ...


@runtime_checkable
class ModuleCatalog(Protocol):
    def list(self) -> tuple[ModuleInfo, ...]: ...
