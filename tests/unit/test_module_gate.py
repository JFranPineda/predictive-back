"""An endpoint belongs to the module whose code it lives in."""

from modules.core.infrastructure.module_gate import module_of


class RollerSheetView:
    pass


RollerSheetView.__module__ = "modules.ut_rollers.interfaces.views"


def as_view(cls):
    def view():
        return None

    view.view_class = cls
    return view


def test_a_class_based_view_belongs_to_its_module():
    assert module_of(as_view(RollerSheetView)) == "ut_rollers"


def test_a_viewset_routed_by_drf_is_found_through_cls():
    def view():
        return None

    view.cls = RollerSheetView
    assert module_of(view) == "ut_rollers"


def test_a_view_outside_the_modules_belongs_to_none():
    def login():
        return None

    login.__module__ = "rest_framework_simplejwt.views"
    assert module_of(login) is None
