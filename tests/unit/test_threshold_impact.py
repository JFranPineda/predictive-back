"""What «Simular impacto» answers: how many machines a criterion would move."""

from modules.thresholds.domain.entities import Status, StatusKind
from modules.thresholds.domain.services import tally_impact

OK = Status("operational", "Operativo", StatusKind.CONDITION, 10)
ALARM = Status("alarm", "Alarma", StatusKind.CONDITION, 20)
STOP = Status("stop", "Parada", StatusKind.CONDITION, 30)


def test_a_verdict_that_stays_the_same_changes_nothing():
    assert tally_impact([(1, "operational", OK)]) == (0, {})


def test_an_equipment_counts_once_at_the_worst_status_it_moves_to():
    changed, by_status = tally_impact([(1, "operational", ALARM), (1, "operational", STOP), (2, None, ALARM)])
    assert changed == 2
    assert by_status == {"stop": 1, "alarm": 1}


def test_a_point_without_verdict_is_not_a_change():
    assert tally_impact([(1, "alarm", None)]) == (0, {})
