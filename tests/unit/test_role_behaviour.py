"""A company's own roles behave as the system role they are built on.

`Role(code)` raised on every role a company created, so a user given
"Gerente General" could not load a single screen. The behaviour now comes from
the role's base, and an unknown one fails closed to the most restricted.
"""

from modules.security.domain.actor import Actor, Role, behaviour_of
from modules.security.domain.policies import VisitRef, can_edit_visit


def test_a_shipped_role_behaves_as_itself():
    assert behaviour_of("technician") is Role.TECHNICIAN
    assert behaviour_of("planner") is Role.PLANNER


def test_an_unknown_role_fails_closed_to_read_only():
    # A role nobody recognises must never be the one that can write.
    assert behaviour_of("gerente_general") is Role.CLIENT_VIEWER
    assert behaviour_of("") is Role.CLIENT_VIEWER
    assert behaviour_of(None) is Role.CLIENT_VIEWER


def visit(participants=frozenset({7}), closed=False):
    return VisitRef(
        id=1, area_id=1, participant_ids=participants, lead_analyst_id=7,
        is_closed=closed, report_issued=False,
    )


def actor(role: Role, *permissions: str, user_id: int = 7) -> Actor:
    return Actor(
        user_id=user_id, company_id=1, role=role,
        permissions=frozenset(permissions), area_ids=None, role_code="custom",
    )


def test_a_manager_cannot_alter_field_data_even_with_the_permission_ticked():
    """The line in the access matrix is drawn by the behaviour, not the box."""
    manager = actor(Role.CLIENT_VIEWER, "measurements.add_reading", "services.close_visit")
    assert can_edit_visit(manager, visit()) is False


def test_the_maintenance_manager_moves_the_plan_but_not_the_readings():
    planner = actor(Role.PLANNER, "services.manage_order", "measurements.add_reading")
    assert can_edit_visit(planner, visit()) is False


def test_a_technician_writes_only_his_own_open_visit():
    technician = actor(Role.TECHNICIAN, "measurements.add_reading")
    assert can_edit_visit(technician, visit()) is True
    assert can_edit_visit(technician, visit(participants=frozenset({99}))) is False
    assert can_edit_visit(technician, visit(closed=True)) is False
