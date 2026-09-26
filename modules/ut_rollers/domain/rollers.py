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
