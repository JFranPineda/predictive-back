"""The monthly summary's verdict per train and service, and its Pareto.

IPSA's `EQUIPOS - CONCLUSIONES.xlsx` counts trains as NORMAL / ALARMA /
PARADA / APAGADO per service. APAGADO is availability, not condition: a train
switched off on the round has no verdict, and counting it as normal would be
the lie the summary exists to avoid.
"""

from __future__ import annotations

from collections.abc import Iterable

# ALERTA sits between alarm and shutdown: IPSA's four-level thermal scale
# (Q9). A plant whose normas never use it does not get an empty column.
STATES = ("normal", "alarm", "alert", "shutdown", "off", "unevaluated")
OPTIONAL_STATES = frozenset({"alert"})
LABELS = {
    "normal": "NORMAL",
    "alarm": "ALARMA",
    "alert": "ALERTA",
    "shutdown": "PARADA",
    "off": "APAGADO",
    "unevaluated": "SIN EVALUAR",
}
_BY_CONDITION = {"operational": "normal", "alarm": "alarm", "alert": "alert", "shutdown": "shutdown"}


def state_for(worst_condition: str | None, *, visited: bool, off: bool) -> str | None:
    """None: the service did not touch the train that month."""
    if worst_condition in _BY_CONDITION:
        return _BY_CONDITION[worst_condition]
    if off:
        return "off"
    return "unevaluated" if visited else None


def pareto(states: Iterable[str | None]) -> dict[str, int]:
    counts = dict.fromkeys(STATES, 0)
    for state in states:
        if state in counts:
            counts[state] += 1
    return counts


def shown_states(tallies: Iterable[dict[str, int]]) -> tuple[str, ...]:
    """The Pareto's columns: every state, but an optional one only if counted."""
    counted = list(tallies)
    return tuple(
        state for state in STATES
        if state not in OPTIONAL_STATES or any(tally.get(state) for tally in counted)
    )
