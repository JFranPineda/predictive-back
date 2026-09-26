"""Fase 3: the working day a chief engineer opens and closes (10-phase-3.md).

Three rules, all enforced on the server:

- once every workday opened for a date is closed, technicians change nothing
  of that date (F3-03);
- nobody photographs or writes an observation about a train without a signed
  ATS for that train in that day's open workday (F3-04);
- a field observation carries its photo, and whether the finding is visible
  in it, before its text (F3-05).

Pure python: the guard and the views bring the rows, this decides.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

# Who manages people, licences, modules and the workday itself is not field
# data: a closed day must not stop a technician changing his own password.
UNLOCKED_MODULES = frozenset({"core", "licensing", "security", "workday"})

# The chief engineer (and the administrator, who holds every permission) is
# who closes the day, so the lock does not apply to whoever can reopen it.
MANAGE = "workday.manage"


def day_closed(open_flags: Iterable[bool]) -> bool:
    """A date is closed once it had workdays and none of them is still open.

    A date nobody opened is not closed: the lock follows the chief engineer's
    act of closing, never the calendar.
    """
    flags = list(open_flags)
    return bool(flags) and not any(flags)


@dataclass(frozen=True, slots=True)
class PermitRef:
    asset_group_id: int
    has_document: bool


def permit_valid(permits: Iterable[PermitRef], asset_group_id: int, *, workday_open: bool) -> bool:
    """An ATS counts once its signed copy is attached, and only while its
    workday is open — the permit is for that day's work, not for the train."""
    if not workday_open:
        return False
    return any(p.asset_group_id == asset_group_id and p.has_document for p in permits)


class ObservationIncompleteError(ValueError):
    pass


def check_observation(*, has_photo: bool, visible: bool | None, text: str) -> None:
    """F3-05, in the order the field sheet asks for it."""
    if not has_photo:
        raise ObservationIncompleteError("Primero la foto de la observación")
    if visible is None:
        raise ObservationIncompleteError("Indica si la observación es visible en la foto")
    if not (text or "").strip():
        raise ObservationIncompleteError("Describe lo que se hizo")


@dataclass(frozen=True, slots=True)
class Work:
    """One line of the day's works (F3-02): a service visit or a correctivo."""

    kind: str
    id: int
    service: str
    order: str
    group: str
    equipment: str
    people: tuple[str, ...]
    started_at: datetime | None
    ended_at: datetime | None


def day_works(works: Iterable[Work]) -> list[Work]:
    """In the order they started; undated ones last, so they stand out."""
    return sorted(
        works,
        key=lambda w: (w.started_at is None, w.started_at.timestamp() if w.started_at else 0, w.kind, w.id),
    )
