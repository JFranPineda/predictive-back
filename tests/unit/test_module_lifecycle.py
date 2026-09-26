"""Installing from /settings/modules runs a module's own setup; uninstalling
runs its teardown; reinstalling runs setup again. Pure fakes, no ORM."""

from modules.core.application.module_installer import ModuleInstaller
from modules.core.domain.manifest import Manifest


class Manifests:
    def __init__(self, *items):
        self.items = items

    def manifests(self):
        return self.items


class States:
    def __init__(self, installed=()):
        self.state = {code: ("installed", "1.0.0") for code in installed}

    def all_states(self):
        return dict(self.state)

    def installed_codes(self):
        return frozenset(code for code, (state, _) in self.state.items() if state == "installed")

    def set_state(self, code, state, version):
        self.state[code] = (state, version)


class Permissions:
    def __init__(self):
        self.calls = []

    def sync(self, module):
        self.calls.append(("sync", module.code))

    def revoke(self, code):
        self.calls.append(("revoke", code))


class Fixtures:
    def load(self, module):
        pass


class Events:
    def publish(self, event):
        pass


class Hooks:
    def __init__(self):
        self.ran = []

    def run(self, dotted_path):
        self.ran.append(dotted_path)


CORE = Manifest(code="core", name="core", version="1.0.0", is_core=True)
ROLLERS = Manifest(
    code="ut_rollers", name="rollers", version="1.0.0", depends=("core",),
    on_install="modules.ut_rollers.application.setup.install",
    on_uninstall="modules.ut_rollers.application.setup.uninstall",
)
PLAIN = Manifest(code="plain", name="plain", version="1.0.0", depends=("core",))


def installer(hooks, installed=("core",)):
    return ModuleInstaller(
        Manifests(CORE, ROLLERS, PLAIN), States(installed), Permissions(), Fixtures(), Events(), hooks
    )


def test_installing_runs_the_modules_setup():
    hooks = Hooks()
    installer(hooks).install("ut_rollers")
    assert hooks.ran == ["modules.ut_rollers.application.setup.install"]


def test_uninstalling_runs_its_teardown():
    hooks = Hooks()
    installer(hooks, installed=("core", "ut_rollers")).uninstall("ut_rollers")
    assert hooks.ran == ["modules.ut_rollers.application.setup.uninstall"]


def test_reinstalling_runs_setup_again():
    hooks = Hooks()
    subject = installer(hooks)
    subject.install("ut_rollers")
    subject.uninstall("ut_rollers")
    subject.install("ut_rollers")
    assert hooks.ran[-1] == "modules.ut_rollers.application.setup.install"
    assert len(hooks.ran) == 3


def test_a_module_without_hooks_installs_as_before():
    hooks = Hooks()
    installer(hooks).install("plain")
    assert hooks.ran == []


def test_the_installer_still_works_with_no_hook_runner():
    installer(None).install("ut_rollers")
