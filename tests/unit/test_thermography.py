"""V3-16: a thermogram's Tmax and its ΔT."""

from decimal import Decimal

from modules.measurements.domain.thermography import delta_of


def test_delta_is_how_much_hotter_than_the_reference():
    assert delta_of(Decimal("72"), Decimal("38")) == Decimal("34")


def test_a_reference_above_tmax_gives_a_negative_delta():
    assert delta_of(Decimal("30"), Decimal("38")) == Decimal("-8")
