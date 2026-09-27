"""The fortnight the log screens show, and where the rest is filed."""

from datetime import date

from modules.core.domain.history import WINDOW_DAYS, archived_before, period_of, window_for
from modules.core.infrastructure.discovery import discover_manifests

TODAY = date(2026, 7, 14)


def test_by_default_the_screen_shows_the_last_fortnight():
    window = window_for(None, None, TODAY)
    assert (window.start, window.end) == (date(2026, 7, 1), TODAY)
    assert window.days == WINDOW_DAYS


def test_moving_the_window_back_never_widens_it():
    window = window_for(None, date(2026, 6, 30), TODAY)
    assert (window.start, window.end) == (date(2026, 6, 17), date(2026, 6, 30))


def test_a_start_older_than_the_window_is_cut_to_it():
    window = window_for(date(2025, 1, 1), None, TODAY)
    assert window.start == date(2026, 7, 1)


def test_a_narrower_range_inside_the_window_is_kept():
    window = window_for(date(2026, 7, 10), date(2026, 7, 12), TODAY)
    assert (window.start, window.end) == (date(2026, 7, 10), date(2026, 7, 12))
    assert window.days == 3


def test_a_start_after_the_end_collapses_to_one_day():
    window = window_for(date(2026, 7, 20), date(2026, 7, 12), TODAY)
    assert window.days == 1


def test_everything_before_the_window_belongs_on_disk():
    assert archived_before(TODAY) == date(2026, 7, 1)
    assert period_of(date(2026, 6, 30)) == "2026-06"


def test_the_two_logs_declare_where_their_history_goes():
    declared = {m.code: m.history_source for m in discover_manifests() if m.history_source}
    assert declared == {
        "core": "modules.core.infrastructure.audit_history.source",
        "activity": "modules.activity.infrastructure.history.source",
    }
