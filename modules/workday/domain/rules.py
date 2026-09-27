"""Fase 3: the working day a chief engineer opens and closes (10-phase-3.md).

Three rules, all enforced on the server:

- once every workday opened for a date is closed, technicians change nothing
  of that date (F3-03);
- nobody fills anything about a train until a service for it has started in
  that day's open workday: its ATS and the three start signatures (Q17, Q19);
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


# Q19: the three who sign a service's start, in the order the form asks.
START_ROLES = ("production_engineer", "service_leader", "plant_supervisor")
ROLE_LABELS = {
    "production_engineer": "Ingeniero de producción",
    "service_leader": "Líder encargado del servicio",
    "plant_supervisor": "Supervisor de planta",
    "crew": "Personal ejecutor",
}
RISK_CATEGORIES = ("high", "medium", "low")
IPERC_LEVELS = ("A", "M", "B")

# Q18: reopening a closed day and closing a service are the chief engineer's
# (and the administrator's); unlocking a service without its start
# signatures is the administrator's alone. Each is its own permission, so
# Usuarios y permisos can hand it to whoever the company decides.
REOPEN = "workday.reopen"
CLOSE_SERVICE = "workday.close_service"
UNLOCK_SERVICE = "workday.unlock_service"


@dataclass(frozen=True, slots=True)
class JobRef:
    """What the guard needs to know about one service of the day."""

    asset_group_id: int
    service_order_id: int | None
    started: bool
    closed: bool


def job_started(signed_roles: Iterable[str], *, unlocked: bool) -> bool:
    """A service starts once its three start signatures are in, or once an
    administrator unlocks it without them (Q19)."""
    return unlocked or set(START_ROLES) <= set(signed_roles)


def job_allows(jobs: Iterable[JobRef], asset_group_id: int, service_order_id: int | None = None) -> bool:
    """Whether today's services let someone fill data of this train: one
    started and not yet closed, for this train and — when both name one —
    this same order."""
    return any(
        job.asset_group_id == asset_group_id
        and job.started
        and not job.closed
        and (
            job.service_order_id is None
            or service_order_id is None
            or job.service_order_id == service_order_id
        )
        for job in jobs
    )


@dataclass(frozen=True, slots=True)
class Step:
    """One row of the ATS table: a step of the activity, one of its hazards,
    the risk it carries, its IPERC evaluation and the controls."""

    step: str
    hazard: str
    risk: str
    level: str
    score: int | None
    controls: str


@dataclass(frozen=True, slots=True)
class CrewMember:
    name: str
    signed: bool


@dataclass(frozen=True, slots=True)
class Ats:
    activity: str
    holder: str
    area: str
    zone: str
    risk_category: str
    ppe: str
    tools: str
    steps: tuple[Step, ...]
    crew: tuple[CrewMember, ...]


def ats_missing(ats: Ats) -> list[str]:
    """What still keeps the ATS from being complete and signed, in the order
    the form reads (Q19: the service closes only with all of it)."""
    missing = []
    for field, label in (
        ("activity", "el nombre de la actividad"),
        ("holder", "el titular de la actividad"),
        ("area", "el área"),
        ("zone", "la zona"),
    ):
        if not getattr(ats, field).strip():
            missing.append(label)
    if ats.risk_category not in RISK_CATEGORIES:
        missing.append("la categoría del riesgo")
    if not ats.ppe.strip():
        missing.append("el EPP")
    if not ats.tools.strip():
        missing.append("los equipos y herramientas")
    if not ats.steps:
        missing.append("al menos un paso de la actividad")
    for number, step in enumerate(ats.steps, start=1):
        if not (step.step.strip() and step.hazard.strip() and step.risk.strip() and step.controls.strip()):
            missing.append(f"el paso {number} completo (paso, peligro, riesgo y controles)")
        elif step.level not in IPERC_LEVELS:
            missing.append(f"la evaluación IPERC del paso {number}")
    if not ats.crew:
        missing.append("el personal ejecutor")
    unsigned = [member.name for member in ats.crew if not member.signed]
    if unsigned:
        missing.append("la firma de " + ", ".join(unsigned))
    return missing


class ServiceNotClosableError(ValueError):
    pass


def check_closable(*, started: bool, closed: bool, missing: list[str]) -> None:
    """Q19: the final hour is signed only over a started service whose ATS is
    complete and signed by everyone on it."""
    if closed:
        raise ServiceNotClosableError("El servicio ya está cerrado")
    if not started:
        raise ServiceNotClosableError("El servicio no tiene sus firmas de inicio")
    if missing:
        raise ServiceNotClosableError("Falta en el ATS: " + "; ".join(missing))


def items_of(steps: Iterable[Step]) -> list[int]:
    """The ATS numbers a step once, however many hazards it lists: rows that
    repeat the step above share its item number."""
    numbers: list[int] = []
    previous = None
    for step in steps:
        key = step.step.strip().lower()
        if numbers and key == previous:
            numbers.append(numbers[-1])
        else:
            numbers.append((numbers[-1] if numbers else 0) + 1)
        previous = key
    return numbers


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
