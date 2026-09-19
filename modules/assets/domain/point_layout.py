"""How a train's measuring points are numbered.

The numbering belongs to the rotating set, not to the machine: report 0023
reads MOTOR on 1-2, REDUCTOR on 3-6 and each bearing housing on two more, up
to 10. Every point code the analyst writes (`HV-7`, `EE-10`) is that number,
so two components of the same train can never repeat one.

Components do not carry the same number of points either. The real reports
show 2+4, 2+4+2+2 and 1+5; a layout that assumes two per machine silently
drops half of a gearbox.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

# Envelope and temperature are read on the horizontal only, as the sheet does.
DEFAULT_AXIS_MAGNITUDES: dict[str, list[str]] = {
    "H": ["vel_rms", "env_accel", "temp"],
    "V": ["vel_rms"],
    "A": ["vel_rms"],
}

# The side a point gets when the component says nothing. A driver is read on
# its free end first, a driven machine on the coupling; anything past the
# second point of a machine has no canonical name and stays generic.
_DRIVER_SIDES = ("free_end", "coupling_end")
_DRIVEN_SIDES = ("coupling_end", "opposite_coupling")


@dataclass(frozen=True)
class ComponentSpec:
    """One machine of the train and how many points are read on it."""

    label: str
    point_count: int = 2
    position: str = "driven"
    equipment_type: str = "motor"
    sides: Sequence[str] = ()


@dataclass(frozen=True)
class PointSpec:
    number: int
    axis: str
    side: str
    component_label: str
    magnitudes: list[str] = field(default_factory=list)
    order: int = 0


def plan_layout(
    components: Sequence[ComponentSpec],
    *,
    axis_magnitudes: dict[str, list[str]] | None = None,
    first_number: int = 1,
) -> list[PointSpec]:
    """Numbers every point of the train in one continuous run."""

    axes = axis_magnitudes or DEFAULT_AXIS_MAGNITUDES
    axis_index = {axis: index for index, axis in enumerate(axes)}
    rows: list[PointSpec] = []
    number = first_number
    for component in components:
        for offset in range(max(component.point_count, 0)):
            side = _side_for(component, offset)
            for axis, magnitudes in axes.items():
                rows.append(
                    PointSpec(
                        number=number,
                        axis=axis,
                        side=side,
                        component_label=component.label,
                        magnitudes=list(magnitudes),
                        order=number * 10 + axis_index[axis],
                    )
                )
            number += 1
    return rows


def next_number(taken: Iterable[int], *, start: int = 1) -> int:
    """The first free point number of a train."""

    numbers = [number for number in taken if number is not None]
    return max(max(numbers) + 1, start) if numbers else start


def _side_for(component: ComponentSpec, offset: int) -> str:
    if offset < len(component.sides):
        return component.sides[offset]
    canonical = _DRIVER_SIDES if component.position == "driver" else _DRIVEN_SIDES
    return canonical[offset] if offset < len(canonical) else "custom"
