"""V3-19: MPd Predictivo and END are separate families."""

from modules.measurements.domain.families import INTERNAL, MPD, NDT, family_for, is_offered


def test_airborne_ultrasound_is_predictive_and_contact_ut_is_ndt():
    assert family_for("ultrasound") == MPD
    assert family_for("ndt_thickness") == NDT


def test_alignment_and_topography_are_predictive():
    assert family_for("alignment") == MPD
    assert family_for("topography") == MPD


def test_maintenance_and_lubrication_are_not_ordered():
    assert family_for("maintenance") == INTERNAL
    assert not is_offered(family_for("lubrication"))
    assert is_offered(family_for("vibration"))


def test_a_new_service_defaults_to_predictive():
    assert family_for("something_new") == MPD
