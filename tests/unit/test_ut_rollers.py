"""V3-21: a roller is judged on its thinnest wall, and order 14778's own
verdicts come back out of the default bands."""

from decimal import Decimal
from pathlib import Path

import pytest

from modules.thresholds.domain.entities import Band, Status, StatusKind
from modules.ut_rollers.domain.rollers import (
    DEFAULT_BANDS,
    headline,
    state_of,
    tally,
)

ORDER = Path(__file__).resolve().parents[3] / "predictive-docs/docs/v2/ORDEN_14778(1).xlsx"
VERDICT = {"ACEPTABLE": "acceptable", "MEDIO": "medium", "INACCESIBLE": "inaccessible",
           "CRÍTICO": "critical"}


def judge(thinnest: Decimal) -> str | None:
    """The default bands with the cascade's own half-open semantics."""
    for band in DEFAULT_BANDS:
        status = Status(band.status_code, band.status_code, StatusKind.CONDITION, 0)
        if Band(status, band.min_value, band.max_value).contains(thinnest):
            return state_of(inaccessible=False, status_code=band.status_code)
    return None


def test_the_headline_is_the_thinnest_wall():
    # AC-01: polín 11 of the 1st group.
    values = [Decimal(v) for v in ("9.23", "8.52", "8.33", "8.65", "7.99", "10.47")]
    assert headline(values) == Decimal("7.99")


def test_a_roller_with_blank_points_is_judged_on_what_was_measured():
    assert headline([None, Decimal("9.1"), None, Decimal("8.7"), None, None]) == Decimal("8.7")
    assert headline([None] * 6) is None


def test_inaccessible_is_a_state_not_a_value():
    # AC-03
    assert state_of(inaccessible=True, status_code=None) == "inaccessible"
    assert tally(["inaccessible", "acceptable"]) == {
        "acceptable": 1, "medium": 0, "inaccessible": 1, "critical": 0,
    }


def test_a_value_with_no_verdict_has_no_state():
    assert state_of(inaccessible=False, status_code=None) is None


def test_the_boundary_is_eight_hundredths_of_a_millimetre_apart():
    assert judge(Decimal("8.00")) == "medium"
    assert judge(Decimal("8.01")) == "acceptable"
    assert judge(Decimal("6.13")) == "critical"


@pytest.mark.skipif(not ORDER.exists(), reason="predictive-docs is not checked out beside the repo")
def test_order_14778_comes_back_as_65_acceptable_and_14_medium():
    # AC-02, against the customer's own workbook.
    import openpyxl

    sheet = openpyxl.load_workbook(ORDER, data_only=True)["SECADORES"]
    states = []
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if row[0] is None or row[9] is None:
            continue
        values = [Decimal(str(v)) for v in row[2:8] if isinstance(v, (int, float))]
        state = judge(headline(values))
        assert state == VERDICT[row[9]], f"{row[0]} polín {row[1]}"
        states.append(state)

    assert tally(states) == {"acceptable": 65, "medium": 14, "inaccessible": 0, "critical": 0}
