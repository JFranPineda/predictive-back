"""Installing PREDICTIVE on the customer's server (v4 Phase 6): the base
catalogue a customer starts from with no books and no demo, and the limits the
norms publish, which are data we load on purpose and never part of that base."""

from datetime import date
from decimal import Decimal

import pytest

from modules.core.domain.base_catalogue import (
    HEADLINES,
    MAGNITUDES,
    ROLES,
    TECHNIQUES,
    UNITS,
)
from modules.thresholds.domain.defaults import STANDARDS
from modules.thresholds.domain.norm_limits import NORM_LIMITS, NORM_VALID_FROM, norm_limit


class TestBaseCatalogue:
    def test_it_has_the_unit_the_rollers_module_asks_for_on_install(self):
        # P0-b: `modules bootstrap` failed on an empty database because the
        # ut_rollers hook looks up the unit `mm`, which only the importers laid.
        assert "mm" in {code for code, *_ in UNITS}

    def test_every_magnitude_names_a_unit_and_a_technique_it_carries(self):
        units = {code for code, *_ in UNITS}
        techniques = {code for code, *_ in TECHNIQUES}
        for code, technique, _es, _en, unit, _aggregation, _decimals in MAGNITUDES:
            assert unit in units, code
            assert technique in techniques, code

    def test_every_headline_is_a_magnitude_of_its_own_technique(self):
        of_technique = {code: technique for code, technique, *_ in MAGNITUDES}
        for technique, magnitude in HEADLINES.items():
            assert of_technique.get(magnitude) == technique, technique

    def test_the_administrator_role_grants_everything(self):
        assert ROLES["company_admin"] == ["*"]

    def test_every_permission_a_role_grants_exists_in_a_module(self):
        # A misspelt permission is dropped without a word when the role is
        # laid down; here it fails instead.
        from modules.core.infrastructure.discovery import discover_manifests

        known = {code for manifest in discover_manifests() for code, _ in manifest.permissions}
        for role, granted in ROLES.items():
            if granted != ["*"]:
                assert set(granted) <= known, (role, set(granted) - known)


class TestNormLimits:
    def test_every_class_of_iso_10816_has_its_published_zones(self):
        for code in ("iso_10816_1", "iso_10816_3"):
            standard = next(s for s in STANDARDS if s.code == code)
            for machine_class in standard.machine_classes:
                assert norm_limit(code, machine_class.code) is not None, (code, machine_class.code)

    def test_iso_10816_3_group_2_rigid_reads_as_the_table_prints_it(self):
        limit = norm_limit("iso_10816_3", "group_2_rigid")
        assert (limit.magnitude, limit.aggregation, limit.unit) == ("vel_rms", "rms", "mm/s")
        assert (limit.low, limit.high) == (Decimal("2.8"), Decimal("4.5"))

    def test_neta_grades_both_comparisons_on_the_hottest_point(self):
        neta = {limit.magnitude: limit for limit in NORM_LIMITS if limit.standard == "neta_mts"}
        assert set(neta) == {"delta_temp", "delta_temp_ambient"}
        assert (neta["delta_temp"].low, neta["delta_temp"].high) == (Decimal("4"), Decimal("15"))
        ambient = neta["delta_temp_ambient"]
        assert (ambient.low, ambient.high) == (Decimal("11"), Decimal("40"))
        assert {limit.aggregation for limit in neta.values()} == {"max"}

    def test_a_limit_is_three_bands_from_operational_to_shutdown(self):
        limit = norm_limit("iso_10816_1", "class_ii")
        assert limit.bands() == (
            ("operational", None, Decimal("2.8")),
            ("alarm", Decimal("2.8"), Decimal("7.1")),
            ("shutdown", Decimal("7.1"), None),
        )

    def test_every_limit_points_at_a_builtin_standard(self):
        builtin = {s.code for s in STANDARDS if s.is_builtin}
        assert {limit.standard for limit in NORM_LIMITS} <= builtin

    def test_they_grade_any_history_a_customer_brings(self):
        # A norm does not start the day it is loaded: readings imported from
        # years of books must be graded by it too.
        assert date(2000, 1, 1) >= NORM_VALID_FROM

    @pytest.mark.parametrize("machine_class", ["class_i", "group_1_flexible"])
    def test_the_rationale_names_the_norm_and_the_class(self, machine_class):
        limit = next(limit for limit in NORM_LIMITS if limit.machine_class == machine_class)
        assert "ISO 10816" in limit.rationale and "·" in limit.rationale
