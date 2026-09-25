"""V3-05: the colour of a train in the assets list."""

from modules.assets.domain.group_status import (
    NOT_EVALUATED,
    StatusView,
    effective_status,
    group_status,
)

OPERATIONAL = StatusView("operational", "Operativo", "#16a34a", 10, True)
ALARM = StatusView("alarm", "Alarma", "#f59e0b", 20, True)
OFF = StatusView("off", "Apagado", "#94a3b8", 0, False, measurable=False)
RUNNING = StatusView("running", "En marcha", "#0ea5e9", 0, False)


def test_the_worst_machine_wins():
    assert group_status([OPERATIONAL, ALARM]) is ALARM


def test_an_off_machine_does_not_show_its_last_verdict():
    assert effective_status(ALARM, OFF) is OFF
    assert effective_status(ALARM, RUNNING) is ALARM


def test_a_train_of_machines_that_are_off_says_so():
    assert group_status([OFF, OFF]) is OFF


def test_a_measured_machine_outranks_one_that_is_off():
    assert group_status([OFF, OPERATIONAL]) is OPERATIONAL


def test_nothing_evaluated_is_never_green():
    assert group_status([NOT_EVALUATED]) is NOT_EVALUATED
    assert group_status([]) is NOT_EVALUATED
