"""The monthly summary's verdict per train and service, and its Pareto.

IPSA's `EQUIPOS - CONCLUSIONES.xlsx` counts trains as NORMAL / ALARMA /
PARADA / APAGADO per service. APAGADO is availability, not condition: a train
switched off on the round has no verdict, and counting it as normal would be
the lie the summary exists to avoid.

The plant's condition states are data: a norma can name ALERTA (IPSA's
thermal scale, Q9) or OBSERVACIÓN (the Pulper Nº 04, Q16). Any state beyond
normal, alarm and shutdown gets its own column, only where it was counted.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

# The default ladder, mildest first; a plant's own states slot in by severity.
STATES = ("normal", "alarm", "alert", "shutdown", "off", "unevaluated")
ALWAYS = frozenset({"normal", "alarm", "shutdown", "off", "unevaluated"})
LABELS = {
    "normal": "NORMAL",
    "alarm": "ALARMA",
    "alert": "ALERTA",
    "shutdown": "PARADA",
    "off": "APAGADO",
    "unevaluated": "SIN EVALUAR",
}
_BY_CONDITION = {"operational": "normal"}


def state_for(worst_condition: str | None, *, visited: bool, off: bool) -> str | None:
    """None: the service did not touch the train that month. A condition keeps
    its own code, except operational, which the summary calls normal."""
    if worst_condition:
        return _BY_CONDITION.get(worst_condition, worst_condition)
    if off:
        return "off"
    return "unevaluated" if visited else None


def columns(conditions_by_severity: Sequence[str] = ()) -> tuple[str, ...]:
    """The Pareto's possible columns: the plant's condition states, mildest
    first, then off and unevaluated. Without the plant's list, the default
    ladder."""
    if not conditions_by_severity:
        return STATES
    states = [_BY_CONDITION.get(code, code) for code in conditions_by_severity]
    return (*dict.fromkeys(states), "off", "unevaluated")


def pareto(states: Iterable[str | None], order: Sequence[str] = STATES) -> dict[str, int]:
    counts = dict.fromkeys(order, 0)
    for state in states:
        if state in counts:
            counts[state] += 1
    return counts


def shown_states(tallies: Iterable[dict[str, int]], order: Sequence[str] = STATES) -> tuple[str, ...]:
    """The Pareto's columns: the usual ones always, any other only if counted."""
    counted = list(tallies)
    return tuple(
        state for state in order
        if state in ALWAYS or any(tally.get(state) for tally in counted)
    )


def label_for(state: str, names: dict[str, str] | None = None) -> str:
    """NORMAL, ALARMA… or the plant's own state name, in capitals."""
    return LABELS.get(state) or (names or {}).get(state, state).upper()
