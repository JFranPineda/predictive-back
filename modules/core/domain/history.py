"""How much of a log a screen shows, and how the rest is filed.

A log that only grows cannot be read by scrolling it: the activity log and the
audit trail answer "what happened lately", so the screen holds two weeks and
nothing else. Everything older lives on disk, one file per month, where anyone
can open it without the application.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

# Two weeks: a fortnight is what a shift manager reads back over, and it keeps
# the query on the part of the table the index actually helps with.
WINDOW_DAYS = 14


@dataclass(frozen=True, slots=True)
class Window:
    """The days a log screen shows: both ends included."""

    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def window_for(since: date | None, until: date | None, today: date, days: int = WINDOW_DAYS) -> Window:
    """The window asked for, cut to `days`.

    The end is what the reader chose (today by default) and the start follows
    from it, so moving the window back never widens it. A start after the end
    is a typed date, not an intent: the window collapses to that one day.
    """
    end = until or today
    earliest = end - timedelta(days=days - 1)
    if since is None or since < earliest:
        return Window(earliest, end)
    return Window(since, max(since, end))


def period_of(day: date) -> str:
    """The file a day is archived into. One per month reads as a ledger."""
    return f"{day:%Y-%m}"


def archived_before(today: date, days: int = WINDOW_DAYS) -> date:
    """The first day still shown; everything before it belongs on disk."""
    return today - timedelta(days=days - 1)
