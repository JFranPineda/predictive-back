"""V3-23: the monthly Pareto and the PDF's trend chart."""

from modules.reports.domain.pareto import pareto, shown_states, state_for
from modules.reports.domain.trend_svg import trend_svg


def test_a_train_is_judged_by_its_worst_condition():
    assert state_for("alarm", visited=True, off=False) == "alarm"
    assert state_for("operational", visited=True, off=True) == "normal"


def test_a_train_switched_off_is_apagado_not_normal():
    assert state_for(None, visited=True, off=True) == "off"


def test_a_visit_with_no_verdict_is_counted_as_not_evaluated():
    assert state_for(None, visited=True, off=False) == "unevaluated"


def test_a_train_the_service_never_touched_is_not_counted():
    assert state_for(None, visited=False, off=False) is None


def test_the_pareto_counts_each_state_once_per_train():
    # IPSA, 21-sep: 17 normal, 1 alarm, 3 shutdown, 20 off.
    states = ["normal"] * 17 + ["alarm"] + ["shutdown"] * 3 + ["off"] * 20 + [None] * 4
    assert pareto(states) == {
        "normal": 17, "alarm": 1, "alert": 0, "shutdown": 3, "off": 20, "unevaluated": 0,
    }


def test_alerta_is_a_column_only_where_a_norma_uses_it():
    # IPSA's thermal scale (Q9) has ALERTA between ALARMA and PARADA; AMBEV's
    # Pareto must not grow an empty column for it.
    without = pareto(["normal", "alarm"])
    with_alert = pareto(["alert", state_for("alert", visited=True, off=False)])
    assert "alert" not in shown_states([without])
    assert shown_states([without, with_alert]).index("alert") == 2
    assert with_alert["alert"] == 2


def test_the_trend_draws_one_line_per_point_and_steps_over_gaps():
    svg = trend_svg(
        ["13 nov", "12 dic", "10 ene"],
        [("1H", [3.02, None, 3.70]), ("1V", [2.66, 1.92, 2.63])],
        unit="mm/s",
    )
    assert svg.count("<polyline") == 2
    # 1H has two measured rounds: two points, not three.
    first = svg.split("<polyline")[1].split("/>")[0]
    assert first.count(",") == 2


def test_a_trend_with_nothing_measured_draws_nothing():
    assert trend_svg(["13 nov"], [("1H", [None])]) == ""
