"""What colour a train shows in a list of trains.

The same two rules as the plant traffic light: the worst machine wins, and an
unmeasurable availability (off, retired) outranks a stale condition. A train
whose machines are all off shows that, not "sin evaluar" — and never green.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StatusView:
    code: str
    name: str
    color: str
    severity: int
    is_condition: bool
    measurable: bool = True


NOT_EVALUATED = StatusView("not_evaluated", "Sin evaluar", "#94a3b8", 0, False, False)


def effective_status(condition: StatusView | None, availability: StatusView | None) -> StatusView:
    if availability is not None and not availability.measurable:
        return availability
    return condition or NOT_EVALUATED


def group_status(members: Sequence[StatusView]) -> StatusView:
    conditions = [status for status in members if status.is_condition]
    if conditions:
        return max(conditions, key=lambda status: status.severity)
    declared = [status for status in members if status.code != NOT_EVALUATED.code]
    return declared[0] if declared else NOT_EVALUATED
