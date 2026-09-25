"""The last time somebody did something to a train (V3-07).

A service visit of any technique counts, and so does a maintenance record:
the column answers "when was this train last touched", whoever touched it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Intervention:
    at: datetime
    what: str
    who: str = ""


def latest(interventions: Iterable[Intervention | None]) -> Intervention | None:
    present = [row for row in interventions if row is not None]
    return max(present, key=lambda row: row.at) if present else None
