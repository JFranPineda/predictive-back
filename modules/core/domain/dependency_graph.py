"""Dependency resolution for module install / uninstall.

Same rules Odoo enforces: you cannot install a module before its dependencies,
and you cannot remove one that something else still needs.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .errors import CircularDependency, MissingDependency, ModuleInUse
from .manifest import Manifest


class DependencyGraph:
    def __init__(self, manifests: Iterable[Manifest]) -> None:
        self._by_code: Mapping[str, Manifest] = {m.code: m for m in manifests}

    def __contains__(self, code: str) -> bool:
        return code in self._by_code

    def get(self, code: str) -> Manifest:
        try:
            return self._by_code[code]
        except KeyError as exc:
            raise MissingDependency(code) from exc

    def install_order(self, code: str, installed: frozenset[str]) -> tuple[str, ...]:
        """Every module that must be installed, dependencies first."""
        order: list[str] = []
        visiting: set[str] = set()

        def visit(current: str) -> None:
            if current in order or current in installed:
                return
            if current in visiting:
                raise CircularDependency(current)
            visiting.add(current)
            for dep in self.get(current).depends:
                visit(dep)
            visiting.discard(current)
            order.append(current)

        visit(code)
        return tuple(order)

    def dependents(self, code: str, installed: frozenset[str]) -> tuple[str, ...]:
        """Installed modules that would break if `code` went away."""
        return tuple(
            sorted(
                other
                for other in installed
                if other != code and code in self._reachable_depends(other)
            )
        )

    def assert_removable(self, code: str, installed: frozenset[str]) -> None:
        manifest = self.get(code)
        if manifest.is_core:
            raise ModuleInUse(code, ("core module",))
        blockers = self.dependents(code, installed)
        if blockers:
            raise ModuleInUse(code, blockers)

    def _reachable_depends(self, code: str) -> frozenset[str]:
        seen: set[str] = set()
        stack = list(self.get(code).depends)
        while stack:
            dep = stack.pop()
            if dep in seen or dep not in self._by_code:
                continue
            seen.add(dep)
            stack.extend(self._by_code[dep].depends)
        return frozenset(seen)
