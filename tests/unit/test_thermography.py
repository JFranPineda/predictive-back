"""V3-16 and Q8: a thermogram's Tmax and the ΔT the technician types."""

from decimal import Decimal

from modules.measurements.domain.thermography import DELTA_TEMP, IR_TMAX, thermogram_values


def test_the_delta_is_kept_as_typed():
    assert thermogram_values(Decimal("72"), Decimal("12.5")) == [
        (IR_TMAX, Decimal("72")),
        (DELTA_TEMP, Decimal("12.5")),
    ]


def test_no_delta_typed_means_no_delta_reading():
    assert thermogram_values(Decimal("72"), None) == [(IR_TMAX, Decimal("72"))]


def test_a_thermogram_without_tmax_still_records_its_delta():
    assert thermogram_values(None, Decimal("4")) == [(IR_TMAX, None), (DELTA_TEMP, Decimal("4"))]
