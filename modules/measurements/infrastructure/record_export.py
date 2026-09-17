"""Builds the record of values as the workbook the customer already uses.

The layout is copied from `TABLA DE TENDENCIAS.xls`, section by section:
a title, the limits in force, one metadata row per round (date, location,
tag, operating conditions, who took the readings), then one block per
magnitude with the component and side columns merged, and the running
parameters at the foot.

The point is that the deliverable leaves the system. A report that has to be
retyped into a spreadsheet is a report the spreadsheet still owns.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

NAVY = "1F3864"
GREY = "D9D9D9"
LIGHT = "F2F2F2"

WHITE_BOLD = Font(bold=True, color="FFFFFF", size=11)
BOLD = Font(bold=True, size=10)
NORMAL = Font(size=10)
SMALL = Font(size=9)

CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)
RIGHT = Alignment(horizontal="right", vertical="center")

THIN = Side(style="thin", color="9E9E9E")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

# Three fixed columns (component, side, point) before the dates start.
FIRST_DATA_COLUMN = 4


@dataclass(frozen=True, slots=True)
class ExportColumn:
    date: str
    order_code: str
    operators: str
    operating: dict[str, str]


@dataclass(frozen=True, slots=True)
class ExportBlock:
    title: str
    unit: str
    aggregation: str
    decimals: int
    rows: tuple[dict, ...]


@dataclass(frozen=True, slots=True)
class ExportBand:
    status: str
    minimum: str
    maximum: str


def build_workbook(
    *,
    equipment: dict,
    columns: list[ExportColumn],
    blocks: list[ExportBlock],
    bands: list[ExportBand],
    operating_labels: dict[str, str],
    title: str,
) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = equipment["tag"][:31] or "Registro"
    last_column = FIRST_DATA_COLUMN + len(columns) - 1

    row = _write_title(sheet, equipment, title, last_column)
    row = _write_limits(sheet, bands, row, last_column)
    row = _write_metadata(sheet, equipment, columns, operating_labels, row, last_column)
    for block in blocks:
        row = _write_block(sheet, block, columns, row, last_column)
    row = _write_operating(sheet, columns, operating_labels, row, last_column)

    _size_columns(sheet, columns)
    # The three label columns stay put while a long history scrolls. As a
    # coordinate, not a cell: A1 is inside the merged title, and openpyxl
    # tries to parse a merged cell as a string and dies.
    sheet.freeze_panes = f"{get_column_letter(FIRST_DATA_COLUMN)}1"

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _write_title(sheet, equipment: dict, title: str, last_column: int) -> int:
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last_column)
    cell = sheet.cell(row=1, column=1, value=title)
    cell.font = Font(bold=True, size=13, color=NAVY)
    cell.alignment = CENTER

    sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=last_column)
    subtitle = sheet.cell(
        row=2,
        column=1,
        value=f"REGISTRO DE VALORES — {equipment['name']} ({equipment['tag']})",
    )
    subtitle.font = Font(bold=True, size=11, color=NAVY)
    subtitle.alignment = CENTER

    sheet.merge_cells(start_row=3, start_column=1, end_row=3, end_column=last_column)
    where = sheet.cell(row=3, column=1, value=f"{equipment['area']} · {equipment['group']}")
    where.font = SMALL
    where.alignment = CENTER
    return 5


def _write_limits(sheet, bands: list[ExportBand], row: int, last_column: int) -> int:
    if not bands:
        return row
    sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=last_column)
    header = sheet.cell(row=row, column=1, value="LÍMITES PERMISIBLES EN VIGOR")
    header.fill = PatternFill("solid", fgColor=NAVY)
    header.font = WHITE_BOLD
    header.alignment = LEFT
    row += 1

    for band in bands:
        sheet.cell(row=row, column=1, value=band.status).font = BOLD
        sheet.cell(row=row, column=2, value=band.minimum).alignment = RIGHT
        sheet.cell(row=row, column=3, value=band.maximum).alignment = RIGHT
        for column in range(1, 4):
            sheet.cell(row=row, column=column).border = BOX
        row += 1
    return row + 1


def _write_metadata(
    sheet, equipment: dict, columns: list[ExportColumn], operating_labels: dict[str, str],
    row: int, last_column: int,
) -> int:
    del operating_labels
    entries = [
        ("FECHA", [column.date for column in columns]),
        ("ORDEN", [column.order_code for column in columns]),
        ("UBICACIÓN", [equipment["area"]] * len(columns)),
        ("TAG EQUIPO", [equipment["tag"]] * len(columns)),
        ("LECTURAS TOMADAS POR", [column.operators for column in columns]),
    ]
    for label, values in entries:
        sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
        cell = sheet.cell(row=row, column=1, value=label)
        cell.font = BOLD
        cell.alignment = LEFT
        cell.fill = PatternFill("solid", fgColor=LIGHT)
        for offset, value in enumerate(values):
            data = sheet.cell(row=row, column=FIRST_DATA_COLUMN + offset, value=value)
            data.font = SMALL
            data.alignment = CENTER
            data.border = BOX
        sheet.cell(row=row, column=1).border = BOX
        row += 1
    del last_column
    return row + 1


def _write_block(
    sheet, block: ExportBlock, columns: list[ExportColumn], row: int, last_column: int
) -> int:
    sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=last_column)
    header = sheet.cell(
        row=row, column=1, value=f"{block.title.upper()} ( {block.unit} — {block.aggregation} )"
    )
    header.fill = PatternFill("solid", fgColor=NAVY)
    header.font = WHITE_BOLD
    header.alignment = LEFT
    row += 1

    for index, label in enumerate(("COMPONENTE", "LADO", "PUNTO"), start=1):
        cell = sheet.cell(row=row, column=index, value=label)
        cell.font = BOLD
        cell.fill = PatternFill("solid", fgColor=GREY)
        cell.alignment = CENTER
        cell.border = BOX
    for offset, column in enumerate(columns):
        cell = sheet.cell(row=row, column=FIRST_DATA_COLUMN + offset, value=column.date)
        cell.font = BOLD
        cell.fill = PatternFill("solid", fgColor=GREY)
        cell.alignment = CENTER
        cell.border = BOX
    row += 1

    first_row = row
    for entry in block.rows:
        sheet.cell(row=row, column=3, value=entry["label"]).font = BOLD
        sheet.cell(row=row, column=3).alignment = CENTER
        sheet.cell(row=row, column=3).border = BOX
        for offset, value in enumerate(entry["values"]):
            cell = sheet.cell(row=row, column=FIRST_DATA_COLUMN + offset)
            # A blank is a round that does not exist; "--" is one that could
            # not be measured. The sheet has always distinguished them.
            cell.value = _number(value, block.decimals) if value is not None else entry["missing"][offset]
            cell.alignment = RIGHT
            cell.border = BOX
            cell.font = NORMAL
        row += 1

    _merge_labels(sheet, block, first_row)
    return row + 1


def _merge_labels(sheet, block: ExportBlock, first_row: int) -> None:
    """Merges the component and side columns the way the printed sheet does.

    A side only merges within its own component: two machines can both have a
    "lado acople" and they are not one run.
    """
    plans = (
        (1, [row["component"] for row in block.rows], BOLD, GREY),
        (2, [f"{row['component']}|{row['side_label']}" for row in block.rows], SMALL, LIGHT),
    )
    for column_index, keys, font, colour in plans:
        for start, length in _runs(keys):
            top = first_row + start
            bottom = top + length - 1
            if bottom > top:
                sheet.merge_cells(
                    start_row=top, start_column=column_index,
                    end_row=bottom, end_column=column_index,
                )
            label = block.rows[start]["component" if column_index == 1 else "side_label"]
            cell = sheet.cell(row=top, column=column_index, value=label)
            cell.font = font
            cell.alignment = CENTER
            cell.fill = PatternFill("solid", fgColor=colour)
            for fill_row in range(top, bottom + 1):
                sheet.cell(row=fill_row, column=column_index).border = BOX


def _runs(keys: list[str]) -> list[tuple[int, int]]:
    """(start, length) of each run of equal consecutive keys."""
    runs: list[tuple[int, int]] = []
    start = 0
    for index in range(1, len(keys) + 1):
        if index == len(keys) or keys[index] != keys[start]:
            runs.append((start, index - start))
            start = index
    return runs


def _write_operating(
    sheet, columns: list[ExportColumn], operating_labels: dict[str, str], row: int, last_column: int
) -> int:
    codes = sorted({code for column in columns for code in column.operating})
    if not codes:
        return row

    sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=last_column)
    header = sheet.cell(row=row, column=1, value="PARÁMETROS DE FUNCIONAMIENTO")
    header.fill = PatternFill("solid", fgColor=NAVY)
    header.font = WHITE_BOLD
    header.alignment = LEFT
    row += 1

    for code in codes:
        sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
        label = sheet.cell(row=row, column=1, value=operating_labels.get(code, code))
        label.font = BOLD
        label.alignment = LEFT
        label.fill = PatternFill("solid", fgColor=LIGHT)
        label.border = BOX
        for offset, column in enumerate(columns):
            cell = sheet.cell(
                row=row, column=FIRST_DATA_COLUMN + offset,
                value=_number(column.operating.get(code), 2) if column.operating.get(code) else "--",
            )
            cell.alignment = RIGHT
            cell.border = BOX
            cell.font = NORMAL
        row += 1
    return row


def _number(value, decimals: int):
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return value
    return round(numeric, decimals)


def _size_columns(sheet, columns) -> None:
    widths = {1: 16, 2: 22, 3: 9}
    for index, width in widths.items():
        sheet.column_dimensions[get_column_letter(index)].width = width
    for offset in range(len(columns)):
        sheet.column_dimensions[get_column_letter(FIRST_DATA_COLUMN + offset)].width = 12
