"""What makes a kind's point template acceptable.

A template is typed row by row, and the two mistakes that actually happened
were a repeated point (1H twice, the error surfacing thirty rows away from its
cause) and a component whose template no longer matched the number of points
it declares (the compressor said 2 and its template carried 4). Both are
checked here, and each problem names the rows that cause it so the editor can
point at them.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

AXES = ("H", "V", "A", "N")
SIDES = (
    "free_end", "coupling_end", "opposite_coupling", "inboard", "outboard",
    "lower", "upper", "custom",
)


@dataclass(frozen=True, slots=True)
class TemplateRowSpec:
    number: int
    axis: str
    side: str = "custom"
    component_label: str = ""


@dataclass(frozen=True, slots=True)
class DeclaredComponent:
    label: str
    point_count: int


@dataclass(frozen=True, slots=True)
class TemplateProblem:
    message: str
    rows: tuple[int, ...] = ()


def check_template(
    rows: Sequence[TemplateRowSpec], components: Sequence[DeclaredComponent]
) -> list[TemplateProblem]:
    """Every problem at once: fixing them one save at a time is how people give up."""
    problems = _row_problems(rows, {component.label for component in components})
    problems += _duplicates(rows)
    problems += _count_mismatches(rows, components)
    return problems


def _row_problems(rows: Sequence[TemplateRowSpec], labels: set[str]) -> list[TemplateProblem]:
    problems = []
    unknown: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        if row.number < 1:
            problems.append(TemplateProblem("El número de punto debe ser 1 o mayor", (index,)))
        if row.axis not in AXES:
            problems.append(TemplateProblem(f"Eje desconocido: {row.axis}", (index,)))
        if row.side not in SIDES:
            problems.append(TemplateProblem(f"Lado desconocido: {row.side}", (index,)))
        if row.component_label and row.component_label not in labels:
            unknown[row.component_label].append(index)
    problems += [
        TemplateProblem(f"El componente {label} no existe en el tipo", tuple(indexes))
        for label, indexes in unknown.items()
    ]
    return problems


def _duplicates(rows: Sequence[TemplateRowSpec]) -> list[TemplateProblem]:
    positions: dict[tuple[int, str], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        positions[(row.number, row.axis)].append(index)
    problems = []
    for (number, axis), indexes in positions.items():
        if len(indexes) < 2:
            continue
        owners = sorted({rows[i].component_label for i in indexes if rows[i].component_label})
        where = f" (en {', '.join(owners)})" if owners else ""
        problems.append(TemplateProblem(f"El punto {number}{axis} está repetido{where}", tuple(indexes)))
    return problems


def _count_mismatches(
    rows: Sequence[TemplateRowSpec], components: Sequence[DeclaredComponent]
) -> list[TemplateProblem]:
    """Rows with no component belong to the whole train, as older kinds wrote
    them, and are not counted against any machine."""
    problems = []
    for component in components:
        indexes = tuple(i for i, row in enumerate(rows) if row.component_label == component.label)
        points = len({rows[i].number for i in indexes})
        if points != component.point_count:
            problems.append(
                TemplateProblem(
                    f"{component.label} declara {component.point_count} puntos "
                    f"y la plantilla tiene {points}",
                    indexes,
                )
            )
    return problems
