"""Plant traffic light (Informes).

Rolls equipment statuses up through Área → Sector → Conjunto and colours each
level. Two rules carry the whole module:

1. **The worst wins.** An area with one equipment in PARADA is not "mostly
   green"; it is red. Averaging statuses is how a plant looks healthy right
   until something breaks.
2. **Not measured is not green.** Equipment that was off, retired or simply
   skipped is counted apart and shown in its own colour. The source RGP had 13%
   of the plant in that bucket; folding it into "operativo" would have inflated
   every indicator in this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from modules.thresholds.domain.entities import Status, StatusKind

NOT_EVALUATED = Status(
    code="not_evaluated",
    name="Sin evaluar",
    kind=StatusKind.AVAILABILITY,
    severity=0,
    color="#94a3b8",
    measurable=False,
)


@dataclass(frozen=True, slots=True)
class Driver:
    """The number behind the colour.

    A red area says something is wrong; "12.42 mm/s" says how wrong, and the
    tag says which machine to walk to. Without them the traffic light is a
    mood, and the analyst opens the spreadsheet anyway.
    """

    value: float
    unit: str
    magnitude_code: str
    higher_is_worse: bool
    equipment_id: int
    equipment_tag: str
    # Who took it and when. A manager looking at a red area asks "since when,
    # and who saw it" before anything else; the board has to answer without
    # anyone being able to change the answer. Two times, because they differ:
    # a round measured in the plant is often typed in at the office later.
    recorded_by: str = ""
    recorded_at: str | None = None
    measured_at: str | None = None


def worst_driver(drivers: list[Driver]) -> Driver | None:
    """The extreme reading of a node, in its own magnitude's direction.

    Thickness and viscosity get worse as they fall, so the minimum is the one
    worth printing — taking the maximum would show the healthiest polín of
    the area and call it the headline.
    """
    if not drivers:
        return None
    higher = [row for row in drivers if row.higher_is_worse]
    lower = [row for row in drivers if not row.higher_is_worse]
    # Mixed directions in one node: the ones that grow are the alarming kind.
    if higher:
        return max(higher, key=lambda row: row.value)
    return min(lower, key=lambda row: row.value)


@dataclass(frozen=True, slots=True)
class EquipmentStatus:
    equipment_id: int
    name: str
    area_id: int
    area_label: str
    sector_id: int
    sector_label: str
    asset_group_id: int
    asset_group_label: str
    technique_code: str
    condition: Status | None
    availability: Status | None
    driver: Driver | None = None

    @property
    def effective(self) -> Status:
        """What the card shows. An unmeasurable availability outranks a stale
        condition: the last NORMAL of an equipment that is now off says nothing
        about it today."""
        if self.availability is not None and not self.availability.measurable:
            return self.availability
        return self.condition or NOT_EVALUATED

    @property
    def counts_for_health(self) -> bool:
        return self.effective.is_condition


@dataclass(frozen=True, slots=True)
class StatusCount:
    status: Status
    count: int


@dataclass(slots=True)
class SummaryNode:
    key: str
    label: str
    level: str
    total: int = 0
    evaluated: int = 0
    counts: list[StatusCount] = field(default_factory=list)
    children: list["SummaryNode"] = field(default_factory=list)
    worst: Status = NOT_EVALUATED
    driver: Driver | None = None

    @property
    def color(self) -> str:
        return self.worst.color

    @property
    def coverage(self) -> float:
        """Share of the equipment that actually produced a verdict. A green
        area with 40% coverage is a scheduling problem, not a healthy area."""
        return round(self.evaluated / self.total, 4) if self.total else 0.0

    def count_of(self, status_code: str) -> int:
        return next((c.count for c in self.counts if c.status.code == status_code), 0)


LEVELS = ("area", "sector", "asset_group")


def worst_of(statuses: list[Status]) -> Status:
    """Highest severity among condition statuses. If nothing was evaluated the
    node is "sin evaluar", never operational."""
    conditions = [s for s in statuses if s.is_condition]
    if not conditions:
        return NOT_EVALUATED
    return max(conditions, key=lambda s: s.severity)


def roll_up(rows: list[EquipmentStatus], levels: tuple[str, ...] = LEVELS) -> list[SummaryNode]:
    """Group by the given levels, deepest last, and colour every node."""
    if not levels:
        return []
    level, rest = levels[0], levels[1:]
    buckets: dict[str, list[EquipmentStatus]] = {}
    labels: dict[str, str] = {}
    for row in rows:
        key = str(getattr(row, f"{level}_id"))
        buckets.setdefault(key, []).append(row)
        labels[key] = getattr(row, f"{level}_label")

    nodes = []
    for key, bucket in buckets.items():
        statuses = [row.effective for row in bucket]
        node = SummaryNode(
            key=f"{level}:{key}",
            label=labels[key],
            level=level,
            total=len(bucket),
            evaluated=sum(1 for row in bucket if row.counts_for_health),
            counts=_count(statuses),
            worst=worst_of(statuses),
            driver=worst_driver([row.driver for row in bucket if row.driver]),
            children=roll_up(bucket, rest),
        )
        nodes.append(node)
    # Worst first: the screen exists to surface what is wrong.
    return sorted(nodes, key=lambda n: (-n.worst.severity, n.label))


def by_technique(rows: list[EquipmentStatus]) -> dict[str, list[SummaryNode]]:
    """One traffic light per service type, as the brief asks. A pump can be
    ALARMA on vibration and OPERATIVO on thermography; merging them loses the
    only thing the summary is for."""
    grouped: dict[str, list[EquipmentStatus]] = {}
    for row in rows:
        grouped.setdefault(row.technique_code, []).append(row)
    return {technique: roll_up(bucket) for technique, bucket in sorted(grouped.items())}


def _count(statuses: list[Status]) -> list[StatusCount]:
    tally: dict[str, tuple[Status, int]] = {}
    for status in statuses:
        current, count = tally.get(status.code, (status, 0))
        tally[status.code] = (current, count + 1)
    return sorted(
        (StatusCount(status=status, count=count) for status, count in tally.values()),
        key=lambda c: (-c.status.severity, c.status.code),
    )
