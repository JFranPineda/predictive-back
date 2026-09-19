"""Reading a spectrum the way the instruments actually export it."""

import pytest

from modules.measurements.domain.spectra import SpectrumFormatError, parse_csv


def test_semicolon_file_with_decimal_commas():
    curve = parse_csv(
        "Frequency (Hz);Amplitude (mm/s)\n0,0;0,01\n1,5;0,42\n3,0;2,80\n4,5;0,31\n"
    )

    assert len(curve) == 4
    assert curve.peak == (3.0, 2.8)
    assert curve.span == (0.0, 4.5)
    assert curve.unit == "mm/s"


def test_comma_file_with_decimal_points():
    curve = parse_csv("freq,amp\n0.0,0.01\n10.5,3.2\n21.0,0.4\n")

    assert curve.peak == (10.5, 3.2)


def test_vendor_preamble_is_skipped_not_rejected():
    """A crew that has to clean a CSV by hand stops exporting it."""
    curve = parse_csv(
        "SKF Microlog\nRuta: EB-228\n\nFreq\tAmp (gs)\n0.0\t0.01\n12.5\t1.8\n25.0\t0.3\n"
    )

    assert len(curve) == 3
    assert curve.unit == "gs"


def test_a_file_without_pairs_is_refused():
    with pytest.raises(SpectrumFormatError):
        parse_csv("informe de vibraciones\nsin datos\n")


def test_the_curve_round_trips_through_its_dict():
    curve = parse_csv("freq,amp\n1.0,2.0\n3.0,4.0\n")

    assert curve.as_dict() == {"freq": [1.0, 3.0], "amp": [2.0, 4.0], "unit": ""}
