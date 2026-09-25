"""V3-30: operating data is kept as whole numbers, except the power factor."""

from decimal import Decimal

from modules.operating_data.domain.precision import decimals_for, to_precision


def test_amperage_is_rounded_half_up_to_a_whole_number():
    assert to_precision(Decimal("45.6"), 0) == Decimal("46")
    assert to_precision(Decimal("45.5"), 0) == Decimal("46")
    assert to_precision(Decimal("1785.4"), 0) == Decimal("1785")


def test_the_power_factor_keeps_two_decimals():
    assert decimals_for("power_factor") == 2
    assert to_precision(Decimal("0.864"), decimals_for("power_factor")) == Decimal("0.86")


def test_everything_else_is_a_whole_number():
    assert decimals_for("rpm") == 0


def test_an_empty_value_stays_empty():
    assert to_precision(None, 0) is None
