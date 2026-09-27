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
VERDICT = {"ACEPTABLE": "acceptable", "MEDIO": "medium", "INACCESIBLE": "inaccessible", "CRÍTICO": "critical"}


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
        "acceptable": 1,
        "medium": 0,
        "inaccessible": 1,
        "critical": 0,
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


# Q15: the press rollers' journals, as the client's report tables print them.

from modules.ut_rollers.domain.rollers import (  # noqa: E402
    NO_FINDING,
    Finding,
    describe_indication,
    journal_state,
    results_summary,
)


def test_a_finding_reads_as_the_summary_writes_it():
    assert describe_indication("crack", Decimal("219.8"), Decimal("12.0")) == (
        "Fisura a 219.8 mm de longitud, profundidad 12.0 mm"
    )
    assert (
        describe_indication("undercut", Decimal("281.7"), Decimal("3")) == "Socavación de 3.0 mm a 281.7 mm"
    )
    assert describe_indication("other", None, None, "Corrosión superficial") == "Corrosión superficial"


def test_the_state_column_follows_access_and_findings():
    assert journal_state("ok", "", []) == NO_FINDING
    assert journal_state("covered", "", []) == "Tapado (Sin acceso)"
    assert journal_state(
        "no_access", "Sin acceso por inicio de operaciones del árbol de transmisión.", []
    ) == ("Sin acceso por inicio de operaciones del árbol de transmisión.")
    assert journal_state("ok", "", ["Fisura a 219.8 mm de longitud, profundidad 12.0 mm"]) == (
        "Presenta fisura a 219.8 mm de longitud, profundidad 12.0 mm."
    )


def test_the_results_summary_lists_every_side_with_its_findings_or_a_dash():
    rows = results_summary(
        ["PRIMERA PRENSA", "SEGUNDA PRENSA"],
        [
            Finding(
                "SEGUNDA PRENSA", "drive", "crack", "Fisura a 342.0 mm de longitud, profundidad 10.0 mm", 13
            ),
            Finding("SEGUNDA PRENSA", "drive", "undercut", "Socavación de 3 mm a 281.7 mm", 3),
            Finding(
                "SEGUNDA PRENSA",
                "transmission",
                "crack",
                "Fisura a 346.1 mm de longitud, profundidad 11.0 mm",
                12,
            ),
        ],
    )
    assert [(r["group"], r["side"], len(r["items"])) for r in rows] == [
        ("PRIMERA PRENSA", "drive", 0),
        ("PRIMERA PRENSA", "transmission", 0),
        ("SEGUNDA PRENSA", "drive", 2),
        ("SEGUNDA PRENSA", "transmission", 1),
    ]
    # In roller order, as the client's table reads.
    assert [item["roller"] for item in rows[2]["items"]] == [3, 13]
    assert rows[2]["items"][0]["kind"] == "Socavación"
