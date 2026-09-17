"""T2: dependency resolution and the real manifests found on disk."""

import pytest

from modules.core.domain.dependency_graph import DependencyGraph
from modules.core.domain.errors import MissingDependency, ModuleInUse
from modules.core.domain.manifest import Manifest


def manifest(code, depends=(), is_core=False):
    return Manifest(code=code, name=code, version="1.0.0", depends=depends, is_core=is_core)


GRAPH = DependencyGraph([
    manifest("core", is_core=True),
    manifest("assets", ("core",)),
    manifest("thresholds", ("core", "assets")),
    manifest("measurements", ("core", "assets", "thresholds")),
    manifest("vibration", ("measurements", "media")),
    manifest("media", ("core",)),
])


class TestInstallOrder:
    def test_dependencies_come_first(self):
        order = GRAPH.install_order("vibration", installed=frozenset())
        assert order.index("core") < order.index("assets") < order.index("measurements")
        assert order.index("measurements") < order.index("vibration")
        assert order[-1] == "vibration"

    def test_already_installed_modules_are_skipped(self):
        order = GRAPH.install_order("measurements", installed=frozenset({"core", "assets"}))
        assert order == ("thresholds", "measurements")

    def test_unknown_module_is_rejected(self):
        with pytest.raises(MissingDependency):
            GRAPH.install_order("crystal_ball", installed=frozenset())


class TestRemoval:
    def test_module_in_use_cannot_be_removed(self):
        installed = frozenset({"core", "assets", "thresholds", "measurements", "vibration", "media"})
        with pytest.raises(ModuleInUse) as exc:
            GRAPH.assert_removable("measurements", installed)
        assert "vibration" in exc.value.blockers

    def test_core_modules_are_never_removable(self):
        with pytest.raises(ModuleInUse):
            GRAPH.assert_removable("core", frozenset({"core"}))

    def test_leaf_module_is_removable(self):
        GRAPH.assert_removable("vibration", frozenset({"core", "assets", "vibration"}))

    def test_transitive_dependents_are_found(self):
        installed = frozenset({"core", "assets", "thresholds", "measurements", "vibration"})
        assert "vibration" in GRAPH.dependents("assets", installed)


class TestRealManifests:
    """Guards against a module declaring a dependency nobody ships."""

    @staticmethod
    def discovered():
        from modules.core.infrastructure.discovery import discover_manifests

        return discover_manifests()

    def test_every_module_declares_a_manifest(self):
        codes = {m.code for m in self.discovered()}
        assert {"core", "security", "assets", "thresholds", "measurements", "media"} <= codes

    def test_every_declared_dependency_exists(self):
        manifests = self.discovered()
        codes = {m.code for m in manifests}
        for item in manifests:
            missing = set(item.depends) - codes
            assert not missing, f"{item.code} depends on unknown {missing}"

    def test_the_whole_catalogue_installs_without_cycles(self):
        manifests = self.discovered()
        graph = DependencyGraph(manifests)
        for item in manifests:
            graph.install_order(item.code, installed=frozenset())

    def test_permissions_are_namespaced_by_module(self):
        for item in self.discovered():
            for code, _ in item.permissions:
                assert code.startswith(f"{item.code}."), f"{code} should start with {item.code}."
