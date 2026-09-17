"""T12: the cascade, the per-technique status vocabulary and the standards.

Limits checked here are the ones found in predictive-docs:
  ISO 10816-3 motors 4.5 / 7.1   `111.ETEI - Soplador # 01..xls`
  EB 228 override    4.5 / 6.5   `TABLA DE TENDENCIAS.xls` (stricter than ISO)
  Technical Assoc.   5.4 / 8.1   pumps
"""

from datetime import date
from decimal import Decimal

import pytest

from modules.thresholds.domain.defaults import (
    ALARM,
    OFF,
    OPERATIONAL,
    RETIRED,
    SHUTDOWN,
    profile_for,
    standard_for,
)
from modules.thresholds.domain.entities import (
    Aggregation,
    Band,
    EvaluationContext,
    Scope,
    StatusKind,
    ThresholdSet,
)
from modules.thresholds.domain.errors import OverlappingBands, StatusNotInProfile
from modules.thresholds.domain.services import (
    declare_availability,
    evaluate,
    resolve,
    validate_against_profile,
    validate_bands,
)


def make_set(set_id, scope, ref, low, high, **kwargs):
    return ThresholdSet(
        id=set_id,
        magnitude_code=kwargs.pop("magnitude_code", "vel_rms"),
        unit_code="mm/s",
        aggregation=kwargs.pop("aggregation", Aggregation.RMS),
        scope=scope,
        scope_ref_id=ref,
        bands=(
            Band(OPERATIONAL, None, Decimal(low)),
            Band(ALARM, Decimal(low), Decimal(high)),
            Band(SHUTDOWN, Decimal(high), None),
        ),
        valid_from=date(2024, 1, 1),
        **kwargs,
    )


ISO = make_set(1, Scope.EQUIPMENT_TYPE, "motor", "4.5", "7.1",
               standard_code="iso_10816_3", machine_class="class_iii")
ISO_20816 = make_set(2, Scope.EQUIPMENT_TYPE, "motor", "3.5", "6.1",
                     standard_code="iso_20816_3", machine_class="class_iii")
TAC = make_set(3, Scope.EQUIPMENT_TYPE, "pump", "5.4", "8.1", standard_code="technical_associates")
EB228 = make_set(4, Scope.EQUIPMENT, 228, "4.5", "6.5", rationale="historial del equipo")

ALL = (ISO, ISO_20816, TAC, EB228)


def ctx(**kwargs):
    base = {"magnitude_code": "vel_rms", "aggregation": Aggregation.RMS}
    return EvaluationContext(**(base | kwargs))


class TestResolution:
    def test_falls_back_to_the_standard_of_the_equipment_type(self):
        context = ctx(equipment_id=999, equipment_type="motor",
                      machine_class="class_iii", standard_code="iso_10816_3")
        assert resolve(ALL, context, date(2026, 1, 1)) is ISO

    def test_equipment_override_beats_the_standard(self):
        context = ctx(equipment_id=228, equipment_type="motor",
                      machine_class="class_iii", standard_code="iso_10816_3")
        assert resolve(ALL, context, date(2026, 1, 1)) is EB228

    def test_pump_and_motor_do_not_share_limits(self):
        context = ctx(equipment_type="pump", standard_code="technical_associates")
        assert resolve(ALL, context, date(2026, 1, 1)) is TAC

    def test_expired_override_returns_the_equipment_to_the_standard(self):
        expired = make_set(5, Scope.EQUIPMENT, 228, "4.5", "6.5", valid_to=date(2025, 12, 31))
        context = ctx(equipment_id=228, equipment_type="motor",
                      machine_class="class_iii", standard_code="iso_10816_3")
        assert resolve((ISO, expired), context, date(2026, 1, 1)) is ISO

    def test_no_criterion_yields_no_verdict(self):
        assert resolve(ALL, ctx(equipment_type="gearbox"), date(2026, 1, 1)) is None


class TestStandardSelection:
    """Switching the standard assigned to an equipment changes its limits, and
    therefore its status, without touching any threshold row."""

    def test_the_assigned_standard_decides_which_limits_apply(self):
        motor = {"equipment_type": "motor", "machine_class": "class_iii"}
        under_10816 = resolve(ALL, ctx(**motor, standard_code="iso_10816_3"), date(2026, 1, 1))
        under_20816 = resolve(ALL, ctx(**motor, standard_code="iso_20816_3"), date(2026, 1, 1))
        assert under_10816 is ISO
        assert under_20816 is ISO_20816

    def test_the_same_value_changes_status_with_the_standard(self):
        value = Decimal("6.5")
        assert evaluate(value, ISO).status.code == "alarm"
        assert evaluate(value, ISO_20816).status.code == "shutdown"

    def test_a_machine_class_the_standard_does_not_define_is_rejected(self):
        assert standard_for("iso_10816_3").has_class("class_iii")
        assert not standard_for("iso_10816_3").has_class("category_i")

    def test_a_hand_written_override_ignores_the_standard_filter(self):
        # EB 228 carries no standard, so it competes whatever is assigned.
        context = ctx(equipment_id=228, equipment_type="motor", standard_code="iso_20816_3")
        assert resolve(ALL, context, date(2026, 1, 1)) is EB228


class TestAggregationIsPartOfTheCriterion:
    """`Gs pico` and `Gs p-p` are both valid ways to report envelope; the source
    reports use one each. They must never resolve to one another."""

    peak = make_set(10, Scope.GLOBAL, None, "2.5", "4.0",
                    magnitude_code="env_accel", aggregation=Aggregation.PEAK)
    peak_to_peak = make_set(11, Scope.GLOBAL, None, "9.0", "15.0",
                            magnitude_code="env_accel", aggregation=Aggregation.PEAK_TO_PEAK)

    def test_each_aggregation_resolves_to_its_own_limits(self):
        sets = (self.peak, self.peak_to_peak)
        as_peak = ctx(magnitude_code="env_accel", aggregation=Aggregation.PEAK)
        as_pp = ctx(magnitude_code="env_accel", aggregation=Aggregation.PEAK_TO_PEAK)
        assert resolve(sets, as_peak, date(2026, 1, 1)) is self.peak
        assert resolve(sets, as_pp, date(2026, 1, 1)) is self.peak_to_peak

    def test_the_same_number_means_different_things(self):
        # 10 gE is a shutdown on the peak scale and an alarm peak-to-peak.
        assert evaluate(Decimal("10"), self.peak).status.code == "shutdown"
        assert evaluate(Decimal("10"), self.peak_to_peak).status.code == "alarm"


class TestEvaluation:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [("3.24", "operational"), ("4.5", "alarm"), ("6.35", "alarm"), ("7.78", "shutdown")],
    )
    def test_iso_bands_reproduce_the_soplador_report(self, value, expected):
        assert evaluate(Decimal(value), ISO).status.code == expected

    def test_the_stricter_override_changes_the_verdict(self):
        assert evaluate(Decimal("6.9"), ISO).status.code == "alarm"
        assert evaluate(Decimal("6.9"), EB228).status.code == "shutdown"

    def test_a_value_without_thresholds_is_not_normal(self):
        result = evaluate(Decimal("99"), None)
        assert result.status is None and result.unmatched


class TestTechniqueProfiles:
    """Each technique has its own vocabulary (point 4 of the brief)."""

    def test_vibration_and_ultrasound_share_the_same_four(self):
        for technique in ("vibration", "ultrasound"):
            codes = [status.code for status in profile_for(technique).options]
            assert codes == ["off", "operational", "alarm", "shutdown"]

    def test_thermography_leads_with_the_condition_states(self):
        codes = [status.code for status in profile_for("thermography").options]
        assert codes == ["operational", "alarm", "shutdown", "off"]

    def test_maintenance_has_availability_states_and_no_alarm(self):
        profile = profile_for("maintenance")
        assert [s.code for s in profile.availability_options] == ["off", "retired", "out_of_service"]
        assert [s.code for s in profile.condition_options] == ["operational"]

    def test_a_vibration_route_cannot_declare_an_equipment_retired(self):
        with pytest.raises(StatusNotInProfile):
            declare_availability(profile_for("vibration"), "retired")

    def test_maintenance_can(self):
        assert declare_availability(profile_for("maintenance"), "retired") is RETIRED

    def test_availability_cannot_be_derived_from_a_value(self):
        with pytest.raises(StatusNotInProfile):
            declare_availability(profile_for("vibration"), "alarm")

    def test_none_of_the_availability_states_is_measurable(self):
        for status in profile_for("maintenance").availability_options:
            assert not status.measurable

    def test_a_set_cannot_hand_out_a_status_the_technique_lacks(self):
        retired_band = ThresholdSet(
            id=20, magnitude_code="temp", unit_code="°C", aggregation=Aggregation.MAX,
            scope=Scope.GLOBAL, scope_ref_id=None, valid_from=date(2024, 1, 1),
            bands=(Band(RETIRED, None, Decimal("80")),),
        )
        with pytest.raises(StatusNotInProfile):
            validate_against_profile(retired_band, profile_for("thermography"))

    def test_a_valid_set_passes_its_profile(self):
        validate_against_profile(ISO, profile_for("vibration"))

    def test_off_is_availability_everywhere_it_appears(self):
        assert OFF.kind is StatusKind.AVAILABILITY
        assert not OFF.measurable


class TestBandValidation:
    def test_overlapping_bands_are_rejected(self):
        overlapping = ThresholdSet(
            id=30, magnitude_code="vel_rms", unit_code="mm/s", aggregation=Aggregation.RMS,
            scope=Scope.GLOBAL, scope_ref_id=None, valid_from=date(2024, 1, 1),
            bands=(
                Band(OPERATIONAL, None, Decimal("5.0")),
                Band(ALARM, Decimal("4.5"), Decimal("7.1")),
            ),
        )
        with pytest.raises(OverlappingBands):
            validate_bands(overlapping)

    def test_contiguous_bands_pass(self):
        validate_bands(ISO)
