"""Where a service order may go from where it is.

Changing it is the administrator's call (V3-27), and even then not every move
makes sense: a cancelled order stays cancelled — its visits are kept readable,
and reviving it would mix an abandoned round into the record.
"""

from __future__ import annotations

PLANNED = "planned"
IN_PROGRESS = "in_progress"
DONE = "done"
CANCELLED = "cancelled"

STATUSES = (PLANNED, IN_PROGRESS, DONE, CANCELLED)

_NEXT: dict[str, frozenset[str]] = {
    PLANNED: frozenset({IN_PROGRESS, DONE, CANCELLED}),
    IN_PROGRESS: frozenset({PLANNED, DONE, CANCELLED}),
    # A round marked done by mistake is reopened, not re-planned.
    DONE: frozenset({IN_PROGRESS}),
    CANCELLED: frozenset(),
}


def can_transition(current: str, target: str) -> bool:
    if target not in STATUSES:
        return False
    return current == target or target in _NEXT.get(current, frozenset())
