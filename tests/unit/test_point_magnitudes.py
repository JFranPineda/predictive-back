"""V3-11: acceleration is read only where the template asks for it."""

from modules.measurements.domain.point_magnitudes import magnitudes_for

VIBRATION = ["vel_rms", "accel_rms", "env_accel"]
OPT_IN = ["accel_rms"]


def test_a_point_whose_template_asks_for_acceleration_gets_it():
    assert magnitudes_for(VIBRATION, OPT_IN, ["vel_rms", "accel_rms"]) == VIBRATION


def test_a_point_whose_template_does_not_ask_keeps_the_usual_ones():
    assert magnitudes_for(VIBRATION, OPT_IN, ["vel_rms"]) == ["vel_rms", "env_accel"]


def test_a_point_outside_any_template_keeps_the_usual_ones():
    assert magnitudes_for(VIBRATION, OPT_IN, None) == ["vel_rms", "env_accel"]


def test_without_opt_in_magnitudes_nothing_changes():
    assert magnitudes_for(VIBRATION, [], None) == VIBRATION
