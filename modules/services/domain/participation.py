"""Who performed a service.

The source reports name an "Inspector Analista" and a "Supervisor", and the
trend sheet signs each round with initials — sometimes two ("HT / AJ"). So a
visit has several people with different roles, and every note, reading and
photo keeps the author that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


class ParticipantRole(StrEnum):
    LEAD_ANALYST = "lead_analyst"
    ASSISTANT = "assistant"
    SUPERVISOR = "supervisor"
    CLIENT_WITNESS = "client_witness"


@dataclass(frozen=True, slots=True)
class Participant:
    user_id: int
    full_name: str
    initials: str
    role: ParticipantRole
    is_external: bool = False
    joined_at: datetime | None = None


class EntryType(StrEnum):
    BACKGROUND = "background"
    OBSERVATION = "observation"
    FAILURE_MODE = "failure_mode"
    FINDING = "finding"
    CONCLUSION = "conclusion"
    RECOMMENDATION = "recommendation"
    ACTION_TAKEN = "action_taken"
    NOTE = "note"


@dataclass(frozen=True, slots=True)
class AuthoredEntry:
    """A dated line of the equipment log, with its author. The reports keep
    these as dated lines, not as one free-text field, which is what lets a 2013
    background sit next to a 2014 conclusion in the same document."""

    id: int
    entry_type: EntryType
    entry_date: date
    text: str
    author_id: int
    author_name: str
    visit_id: int | None = None


@dataclass(frozen=True, slots=True)
class ServiceAuthorship:
    """What the "who did this service" screen shows for one visit."""

    visit_id: int
    equipment_id: int
    equipment_name: str
    technique_code: str
    visited_at: datetime
    participants: tuple[Participant, ...]
    entries: tuple[AuthoredEntry, ...]
    reading_count: int
    media_count: int
    is_closed: bool
    report_issued: bool

    @property
    def lead(self) -> Participant | None:
        return next((p for p in self.participants if p.role is ParticipantRole.LEAD_ANALYST), None)

    @property
    def supervisor(self) -> Participant | None:
        return next((p for p in self.participants if p.role is ParticipantRole.SUPERVISOR), None)

    @property
    def signature(self) -> str:
        """The "LECTURAS TOMADAS POR" cell of the trend sheet: 'HT / AJ'."""
        return " / ".join(p.initials or p.full_name for p in self.participants if p.initials or p.full_name)

    def entries_of(self, entry_type: EntryType) -> tuple[AuthoredEntry, ...]:
        return tuple(e for e in self.entries if e.entry_type is entry_type)

    def authored_by(self, user_id: int) -> bool:
        return any(p.user_id == user_id for p in self.participants)
