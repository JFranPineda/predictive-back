"""UT on rollers (V3-21): six wall thicknesses per roller, judged on the
thinnest one, and the four-way tally the customer's order ends with.

The verdict itself is not decided here: each reading is graded by the
thresholds cascade like any other. This is what turns six graded readings
into one roller's state, and a sheet of rollers into the summary table.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

POINTS = 6
MAGNITUDE = "roller_thickness"
TECHNIQUE = "ndt_rollers"

# The client's four words, in the order the order prints them.
STATES = ("acceptable", "medium", "inaccessible", "critical")

# The rollers reuse the plant's severity scale, so the traffic light and every
# other screen rank them like any other finding; the technique only renames
# the three conditions the way the UT report calls them.
STATE_OF_STATUS = {"operational": "acceptable", "alarm": "medium", "shutdown": "critical"}
LABELS = {"operational": "Aceptable", "alarm": "Medio", "shutdown": "Crítico"}

# Inferred from order 14778 (79 rollers of IPSA's dryer groups): every roller
# the order calls MEDIO has its thinnest wall at 8.00 mm or below, every
# ACEPTABLE one at 8.01 or above. The order has no CRÍTICO roller, so that cut
# is an assumption to confirm with the client (Q15): 75 % of the 8.18 mm wall
# of the 8" schedule-40 tube they are made of. Both are editable afterwards in
# Configuración → Umbrales.
MEDIUM_BELOW = Decimal("8.01")
CRITICAL_BELOW = Decimal("6.14")


@dataclass(frozen=True, slots=True)
class DefaultBand:
    status_code: str
    min_value: Decimal | None
    max_value: Decimal | None


# Half-open [min, max), as every band of the cascade: lower is worse.
DEFAULT_BANDS = (
    DefaultBand("shutdown", None, CRITICAL_BELOW),
    DefaultBand("alarm", CRITICAL_BELOW, MEDIUM_BELOW),
    DefaultBand("operational", MEDIUM_BELOW, None),
)


def headline(values: Iterable[Decimal | None]) -> Decimal | None:
    """The roller's number: its thinnest measured wall."""
    measured = [value for value in values if value is not None]
    return min(measured) if measured else None


def state_of(*, inaccessible: bool, status_code: str | None) -> str | None:
    """INACCESIBLE is "not measured, and why" — never a thickness. A roller
    with values but no verdict (no limits configured) has no state yet."""
    if inaccessible:
        return "inaccessible"
    return STATE_OF_STATUS.get(status_code or "")


def tally(states: Iterable[str | None]) -> dict[str, int]:
    counts = dict.fromkeys(STATES, 0)
    for state in states:
        if state in counts:
            counts[state] += 1
    return counts


# ---------------------------------------------------------------- journals (Q15)
#
# The press rollers' journals ("muñones") are inspected for cracks, side by
# side: per roller its diameter, external and total length, and what was
# found. The results summary the report opens with is those findings, row by
# row; a roller with none reads "Sin fisuras presentes en el muñón de polín".

SIDES = {"drive": "Lado mando", "transmission": "Lado transmisión"}
ACCESS = {"ok": "Con acceso", "covered": "Tapado (Sin acceso)", "no_access": "Sin acceso"}
KIND_LABELS = {"crack": "Fisura", "undercut": "Socavación", "other": "Otra"}
NO_FINDING = "Sin fisuras presentes en el muñón de polín."
# The norma the thickness scale lives in (Q15): its bands are "from A to B,
# state W", edited from Normas like any other.
NORMA_CODE = "ut_rollers_thickness"
NORMA_NAME = "UT en rodillos · espesor mínimo de pared"
NORMA_SOURCE = "Escala por espesor mínimo del rodillo: Aceptable, Medio, Crítico (editable)"


def _mm(value: Decimal | None) -> str:
    """One decimal, as the report writes a length or a depth: 12.0 mm."""
    return "—" if value is None else f"{value:.1f}"


def describe_indication(
    kind: str, length_mm: Decimal | None, depth_mm: Decimal | None, notes: str = ""
) -> str:
    """The summary's wording: "Fisura a 219.8 mm de longitud, profundidad
    12.0 mm", "Socavación de 3 mm a 281.7 mm"."""
    if kind == "crack":
        text = f"Fisura a {_mm(length_mm)} mm de longitud"
        return f"{text}, profundidad {_mm(depth_mm)} mm" if depth_mm is not None else text
    if kind == "undercut":
        where = f" a {_mm(length_mm)} mm" if length_mm is not None else ""
        return f"Socavación de {_mm(depth_mm)} mm{where}" if depth_mm is not None else f"Socavación{where}"
    return notes.strip() or KIND_LABELS.get(kind, kind)


def journal_state(access: str, access_note: str, findings: Iterable[str]) -> str:
    """What the detail table's ESTADO column says when nobody wrote it."""
    if access == "covered":
        return ACCESS["covered"]
    if access == "no_access":
        return access_note.strip() or ACCESS["no_access"]
    found = [text for text in findings if text]
    if not found:
        return NO_FINDING
    return "Presenta " + "; ".join(text[0].lower() + text[1:] for text in found) + "."


@dataclass(frozen=True, slots=True)
class Finding:
    group: str
    side: str
    kind: str
    description: str
    roller: int | None


def results_summary(groups: Iterable[str], findings: Iterable[Finding]) -> list[dict]:
    """The report's "Resumen de resultados": every group and side, in order,
    with its findings — or a dash, as the client's table prints it."""
    by_key: dict[tuple[str, str], list[Finding]] = {}
    for finding in findings:
        by_key.setdefault((finding.group, finding.side), []).append(finding)
    rows = []
    for group in groups:
        for side in SIDES:
            items = sorted(by_key.get((group, side), []), key=lambda f: f.roller or 0)
            rows.append(
                {
                    "group": group,
                    "side": side,
                    "side_label": SIDES[side],
                    "items": [
                        {
                            "kind": KIND_LABELS.get(f.kind, f.kind),
                            "description": f.description,
                            "roller": f.roller,
                        }
                        for f in items
                    ],
                }
            )
    return rows
