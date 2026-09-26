"""V3-17: the captured example, reproduced.

Captura 6 del Word — an "Alignment Results" report from SKF — gives the exact
numbers this test replays: four As Found values, three of which fail, and
their four As Corrected counterparts, all of which pass.
"""

from decimal import Decimal

import pytest

from modules.alignment.domain.tolerances import (
    DEFAULT_TIERS,
    AxisValues,
    InvalidTiersError,
    Tolerance,
    check_tiers,
    default_tolerance_for,
    evaluate,
    tier_for,
    within,
)

# A tolerance permissive enough on parallel to fail only the two large ones,
# and tight enough on angular that neither of the small correct values
# happens to slip through by accident.
TOLERANCE = Tolerance(parallel_mm=Decimal("0.10"), angular_mm_per_100mm=Decimal("0.10"))

AS_FOUND = AxisValues(
    angular_h=Decimal("1.00"), parallel_h=Decimal("1.03"),
    angular_v=Decimal("-0.01"), parallel_v=Decimal("0.28"),
)
AS_CORRECTED = AxisValues(
    angular_h=Decimal("-0.06"), parallel_h=Decimal("-0.03"),
    angular_v=Decimal("0.00"), parallel_v=Decimal("0.05"),
)


def test_the_as_found_phase_matches_the_capture():
    verdict = evaluate(AS_FOUND, TOLERANCE)
    assert verdict.angular_h is False
    assert verdict.parallel_h is False
    assert verdict.angular_v is True
    assert verdict.parallel_v is False
    assert not verdict.all_ok


def test_the_as_corrected_phase_matches_the_capture():
    verdict = evaluate(AS_CORRECTED, TOLERANCE)
    assert verdict.angular_h is True
    assert verdict.parallel_h is True
    assert verdict.angular_v is True
    assert verdict.parallel_v is True
    assert verdict.all_ok


def test_a_negative_value_is_judged_by_its_magnitude():
    assert within(Decimal("-0.40"), Decimal("0.10")) is False
    assert within(Decimal("-0.05"), Decimal("0.10")) is True


def test_a_missing_value_has_no_verdict():
    assert within(None, Decimal("0.10")) is None
    values = AxisValues(angular_h=None, parallel_h=None, angular_v=None, parallel_v=None)
    verdict = evaluate(values, TOLERANCE)
    assert not verdict.all_ok  # nothing measured is not "all fine"


def test_tolerance_tightens_as_speed_climbs():
    slow = default_tolerance_for(600)
    fast = default_tolerance_for(3600)
    assert fast.parallel_mm < slow.parallel_mm
    assert fast.angular_mm_per_100mm < slow.angular_mm_per_100mm


# Q10: the RPM chart is a norma's scale, edited from Normas.


def test_a_norma_scale_picks_its_tier_by_speed():
    scale = [(1500, Decimal("0.08"), Decimal("0.06")), (None, Decimal("0.04"), Decimal("0.03"))]
    assert tier_for(1200, scale) == Tolerance(Decimal("0.08"), Decimal("0.06"))
    assert tier_for(1500, scale) == Tolerance(Decimal("0.04"), Decimal("0.03"))
    assert tier_for(1200, []) is None


def test_the_tiers_can_come_in_any_order():
    scale = [(None, Decimal("0.03"), Decimal("0.03")), (1000, Decimal("0.10"), Decimal("0.10"))]
    assert tier_for(900, scale) == Tolerance(Decimal("0.10"), Decimal("0.10"))


@pytest.mark.parametrize(
    ("tiers", "message"),
    [
        ([], "al menos"),
        ([(None, Decimal("0.1"), Decimal("0.1")), (1000, Decimal("0.1"), Decimal("0.1"))], "último"),
        ([(2000, Decimal("0.1"), Decimal("0.1")), (1000, Decimal("0.1"), Decimal("0.1"))], "menor a mayor"),
        ([(1000, Decimal("0"), Decimal("0.1"))], "mayores que cero"),
    ],
)
def test_a_scale_reads_top_to_bottom(tiers, message):
    with pytest.raises(InvalidTiersError, match=message):
        check_tiers(tiers)


def test_the_shipped_chart_is_a_valid_scale():
    check_tiers(list(DEFAULT_TIERS))
