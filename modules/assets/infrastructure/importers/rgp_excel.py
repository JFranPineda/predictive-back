"""Reads the customer's RGP workbook (`VIBRACION <year> <plant>.xls`).

Both the 6-column layout (asset master only) and the 8-column one (with status,
conclusions and recommendations) are supported; the header row decides.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import xlrd

from dataclasses import replace

from modules.assets.domain.rgp import RgpRow, build_row

_CARRY_COLUMNS = ("area", "sector", "group")

_TAG_LINE = re.compile(r"TAG\s*:\s*[A-Z0-9\-]+", re.IGNORECASE)

_HEADERS = {
    "area": "area",
    "sector": "sector",
    "conjunto rotativo": "group",
    "equipo": "equipment",
    "frecuencia": "frequency",
    "estado": "status",
    "conclusiones": "conclusion",
    "recomendaciones": "recommendation",
}


def read_rgp(path: str | Path) -> Iterator[RgpRow]:
    book = xlrd.open_workbook(str(path))
    sheet = book.sheet_by_index(0)
    header_row, columns = _locate_header(sheet)
    carried: dict[str, str] = {}

    pending: RgpRow | None = None
    for row_index in range(header_row + 1, sheet.nrows):
        cells = {
            field: _cell(sheet, row_index, column) for field, column in columns.items()
        }
        for field in _CARRY_COLUMNS:
            if cells.get(field):
                carried[field] = cells[field]
        if not cells.get("equipment"):
            continue

        row = build_row(cells, carried, source_row=row_index + 1)
        if _is_continuation(cells["equipment"]):
            # A bare "TAG:MB111003B" continues the line above it. Emitting it
            # as its own equipment is how one motor becomes two.
            pending = _merge(pending, row) if pending else row
            continue
        if pending is not None:
            yield pending
        pending = row
    if pending is not None:
        yield pending


def _is_continuation(equipment_cell: str) -> bool:
    """True when the cell carries only a TAG and no component name."""
    without_tag = _TAG_LINE.sub("", equipment_cell or "").strip(" -\n\t")
    return not without_tag


def _merge(previous: RgpRow, continuation: RgpRow) -> RgpRow:
    from modules.assets.domain.tag import parse

    tag = continuation.client_tag or previous.client_tag
    return replace(
        previous,
        client_tag=tag,
        equipment_type=previous.equipment_type or (parse(tag).guessed_type if tag else None),
        frequency=previous.frequency or continuation.frequency,
        condition_status=previous.condition_status or continuation.condition_status,
        availability_status=previous.availability_status or continuation.availability_status,
        conclusion=previous.conclusion or continuation.conclusion,
        recommendation=previous.recommendation or continuation.recommendation,
    )


def _locate_header(sheet) -> tuple[int, dict[str, int]]:
    for row_index in range(min(12, sheet.nrows)):
        found: dict[str, int] = {}
        for column in range(sheet.ncols):
            key = _cell(sheet, row_index, column).strip().lower()
            if key in _HEADERS:
                found[_HEADERS[key]] = column
        if "equipment" in found and "area" in found:
            return row_index, found
    raise ValueError("No RGP header row found (expected 'Area' and 'Equipo')")


def _cell(sheet, row: int, column: int) -> str:
    if row >= sheet.nrows or column >= sheet.ncols:
        return ""
    value = sheet.cell_value(row, column)
    if isinstance(value, float) and value == int(value):
        value = int(value)
    return str(value).strip()
