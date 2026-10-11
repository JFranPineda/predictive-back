"""Nobody hands out more than they hold (T5, 10 Oct 2026)."""

from modules.security.domain.actor import Actor, Role
from modules.security.domain.policies import handing_out_refusal, is_admin


def _actor(role: Role, *permissions: str) -> Actor:
    return Actor(user_id=1, company_id=1, role=role, permissions=frozenset(permissions))


MANAGER = _actor(Role.PLANNER, "security.manage_role", "security.manage_user", "assets.view_equipment")
ADMIN = _actor(Role.COMPANY_ADMIN, "security.manage_role")


def test_an_admin_hands_out_anything():
    assert is_admin(ADMIN)
    assert handing_out_refusal(ADMIN, {"core.manage_modules"}, Role.COMPANY_ADMIN) is None


def test_a_manager_hands_out_what_they_hold():
    assert handing_out_refusal(MANAGER, {"assets.view_equipment"}, Role.TECHNICIAN) is None


def test_a_manager_cannot_hand_out_what_they_do_not_hold():
    reason = handing_out_refusal(MANAGER, {"assets.view_equipment", "core.manage_modules"}, Role.TECHNICIAN)
    assert reason and "core.manage_modules" in reason


def test_a_manager_cannot_make_an_administrator():
    assert handing_out_refusal(MANAGER, set(), Role.COMPANY_ADMIN)
    assert handing_out_refusal(MANAGER, set(), Role.PLATFORM_ADMIN)
