"""V3-26 / V3-27: the ledger's filter and an order's status moves."""

from datetime import date

from modules.services.domain.order_filter import OrderFilter, order_filter_from
from modules.services.domain.order_status import can_transition


def test_a_cancelled_order_stays_cancelled():
    assert not can_transition("cancelled", "in_progress")
    assert not can_transition("cancelled", "planned")


def test_the_usual_moves_are_allowed():
    assert can_transition("planned", "in_progress")
    assert can_transition("in_progress", "done")
    assert can_transition("done", "in_progress")
    assert can_transition("planned", "cancelled")


def test_a_done_order_is_reopened_not_replanned():
    assert not can_transition("done", "planned")


def test_an_unknown_status_is_never_a_destination():
    assert not can_transition("planned", "archived")


def test_the_filter_reads_the_query_string():
    parsed = order_filter_from({"q": " MPd-AV ", "technique": "vibration", "from": "2026-09-01"})
    assert parsed == OrderFilter(text="MPd-AV", technique="vibration", date_from=date(2026, 9, 1))


def test_a_half_typed_date_is_ignored():
    assert order_filter_from({"to": "2026-09"}).date_to is None
