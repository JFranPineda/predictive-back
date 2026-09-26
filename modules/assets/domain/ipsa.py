"""How IPSA's monthly workbooks say things, and what the system calls them
(V3-37, `docs/v3/tickets/11-ipsa-context.md`).

Forty-seven books typed by hand over a year: the same idea is written three
ways, the column dates are sometimes text and once line speeds, and one point
is labelled as the one before it. Every rule that reads that mess lives here,
pure, so it can be tested against the sheets' own strings.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

# The column's verdict, as written. SIN ACCESO is "not measured" with a
# reason; APAGADO is availability. OBSERVACIÓN has no counterpart yet (the
# client has not said where it sits), so it travels as itself.
STATES = {
    "NORMAL": "normal",
    "ACEPTABLE": "normal",
    "OBSERVACION": "observation",
    "ALARMA": "alarm",
    "ALERTA": "alert",
    "PARADA": "shutdown",
    "PARDA": "shutdown",
    "APAGADO": "off",
    "SIN ACCESO": "no_access",
}
CONDITION_OF = {"normal": "operational", "alarm": "alarm", "shutdown": "shutdown"}

MONTHS = {
    "ENE": 1,
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "ABR": 4,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AGO": 8,
    "AUG": 8,
    "SEP": 9,
    "SET": 9,
    "OCT": 10,
    "NOV": 11,
    "DIC": 12,
    "DEC": 12,
}

AREAS = {
    "FILTRACION": ("FIL", "Filtración"),
    "SECADORES": ("SEC", "Secadores"),
    "MP3": ("MP3", "MP3"),
    "MESA PLANA": ("MPL", "Mesa plana"),
    "SALA DE CORTES": ("SDC", "Sala de cortes"),
}

COMPONENT_TYPES = (
    ("CHUMACERA", "bearing_housing"),
    ("MOTOR", "motor"),
    ("BOMBA", "pump"),
    ("REDUCTOR", "gearbox"),
    ("ROLLO", "roller"),
)

# The rows of a registro de valores: velocity on three axes, envelope once.
LABEL = re.compile(r"^\s*([HVAE])([VE])\s*-\s*(\d+)\s*$")
SPEED = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*m\s*/\s*s\s*$", re.IGNORECASE)
TEXT_DATE = re.compile(r"^\s*'?(\d{1,2})\s*-+\s*([A-Za-zÁÉÍÓÚáéíóú]{3})[A-Za-z.]*\s*-?\s*(\d{2,4})\s*'?$")


def plain(text: str) -> str:
    """Upper case, no accents, single spaces: `Filtración ` == `FILTRACION`."""
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.upper().split())


def state_of(raw) -> str | None:
    return STATES.get(plain(raw)) if raw not in (None, "") else None


def area_of(raw) -> tuple[str, str]:
    key = plain(raw)
    return AREAS.get(key, (key[:3] or "GEN", str(raw or "General").strip().title()))


def component_type(name: str) -> str:
    key = plain(name)
    for needle, equipment_type in COMPONENT_TYPES:
        if needle in key:
            return equipment_type
    return "other"


def component_name(raw: str) -> str:
    """`MOTOR1` is the motor: a digit glued to the word is a typo, not a
    second motor (the books that write it have only one)."""
    return re.sub(r"(?<=[A-ZÁÉÍÓÚ])\d+$", "", " ".join(str(raw).split()))


def parse_label(raw) -> tuple[str, str | None, int] | None:
    """`HV-1` → velocity on H at point 1; `EE-1` → the envelope of point 1."""
    match = LABEL.match(str(raw or ""))
    if match is None:
        return None
    first, kind, number = match.groups()
    if kind == "E":
        return "env_accel", None, int(number)
    return "vel_rms", first, int(number)


def point_of(raw) -> tuple[int, str] | None:
    """The PUNTO cell: `3`, or `7\\nINFERIOR` on the presses' housings."""
    if isinstance(raw, (int, float)):
        return int(raw), "custom"
    match = re.match(r"^\s*(\d+)\s*(.*)$", str(raw or ""), re.DOTALL)
    if match is None:
        return None
    note = plain(match.group(2))
    side = {"INFERIOR": "lower", "SUPERIOR": "upper"}.get(note, "custom")
    return int(match.group(1)), side


def text_date(raw) -> date | None:
    """`'10-Sep-25'`, `'14-Dic.24'`, `'14--DIC-2024'`."""
    match = TEXT_DATE.match(str(raw or ""))
    if match is None:
        return None
    day, month, year = match.groups()
    month_number = MONTHS.get(plain(month)[:3])
    if month_number is None:
        return None
    full_year = int(year) + (2000 if len(year) == 2 else 0)
    try:
        return date(full_year, month_number, int(day))
    except ValueError:
        return None


MONTH_NAMES = frozenset(
    {
        "ENERO",
        "FEBRERO",
        "MARZO",
        "ABRIL",
        "MAYO",
        "JUNIO",
        "JULIO",
        "AGOSTO",
        "SETIEMBRE",
        "SEPTIEMBRE",
        "OCTUBRE",
        "NOVIEMBRE",
        "DICIEMBRE",
    }
)


def load_condition(take: str) -> str | None:
    """What the machine was carrying on that take: `TOMA 10 CARGA 100%` →
    `CARGA 100 %`. A month name or a bare take number says nothing."""
    rest = re.sub(r"^\s*(T\d+\s*-\s*)?TOMA\s*\d+\s*", "", str(take or ""), flags=re.IGNORECASE).strip()
    if not rest or plain(rest) in MONTH_NAMES:
        return None
    return re.sub(r"(\d)\s*%", r"\1 %", " ".join(rest.split()))


def line_speed(raw) -> Decimal | None:
    """Book 029 wrote the paper machine's speed where the dates go."""
    match = SPEED.match(str(raw or ""))
    return Decimal(match.group(1).replace(",", ".")) if match else None


def book_number(filename: str) -> str | None:
    """`Equipo # 010._ …` → `10`; `Equipo FDR #02. …` → `FDR02`."""
    fdr = re.search(r"FDR\s*#\s*(\d+)", filename, re.IGNORECASE)
    if fdr:
        return f"FDR{int(fdr.group(1)):02d}"
    number = re.search(r"#\s*(\d+)", filename)
    return str(int(number.group(1))) if number else None


def group_code(number: str) -> str:
    return f"fdr-{number[3:]}" if number.startswith("FDR") else f"eq-{int(number):02d}"


def kind_for(types: list[str]) -> str:
    present = set(types)
    if present == {"motor", "pump"}:
        return "motor_pump"
    if "gearbox" in present and "bearing_housing" in present:
        return "motor_gearbox_bearings" if "motor" in present else "bearing_gearbox"
    if present == {"motor", "gearbox"}:
        return "motor_gearbox"
    return "standalone"


def limit_of(label: str) -> tuple[str, str | None] | None:
    """(magnitude, standard) of a V. LÍMITES table, from its title."""
    key = plain(label)
    if "ENVOLVENTE" in key:
        return "env_accel", None
    if "ADAPTACION DE DISENO" in key:
        return "vel_rms", "design"
    if "TECHNICAL ASSOCIATES" in key or "BOMBAS" in key:
        return "vel_rms", "technical_associates"
    if "20816" in key:
        return "vel_rms", "iso_20816_3"
    if "10816" in key:
        return "vel_rms", "iso_10816_3"
    return None


def order_code(technique: str, day: date, take: int) -> str:
    """One order per round date, plant-wide. A second or third take of the
    same day (Pulper Nº 04 on 18-sep: empty, with water, with 1 t) is its own
    column in the book, so it is its own order: `-2`, `-3`."""
    prefix = {"vibration": "IPSA-AV", "thermography": "IPSA-TM"}[technique]
    return f"{prefix}-{day:%Y%m%d}" + (f"-{take}" if take > 1 else "")


@dataclass(frozen=True, slots=True)
class Limit:
    label: str
    normal: Decimal
    stop: Decimal


@dataclass(slots=True)
class Column:
    index: int
    day: date | None
    source: str
    take: str
    state: str | None
    raw_state: str
    speed: Decimal | None = None


@dataclass(slots=True)
class ValueRow:
    component: str
    point: int
    side: str
    magnitude: str
    axis: str | None
    label: str
    values: dict[int, Decimal] = field(default_factory=dict)


@dataclass(slots=True)
class Note:
    sheet: str
    section: str
    day: date
    text: str


@dataclass(slots=True)
class Book:
    filename: str
    number: str
    area: str
    header_name: str
    header_state: str | None
    inspection_day: date | None
    analyst: str
    field_inspector: str
    instrument: str
    columns: list[Column] = field(default_factory=list)
    rows: list[ValueRow] = field(default_factory=list)
    operating: dict[str, dict[int, Decimal]] = field(default_factory=dict)
    limits: list[Limit] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)
    # The Alarma / Parada rows under the values: the limit the analyst applied
    # column by column, which is not always the one the V. LÍMITES table says.
    column_limits: dict[str, set[Decimal]] = field(default_factory=dict)
    thermo_day: date | None = None
    thermo_state: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def code(self) -> str:
        return group_code(self.number)

    def components(self) -> list[str]:
        seen: list[str] = []
        for row in self.rows:
            if row.component not in seen:
                seen.append(row.component)
        return seen

    def measured_columns(self) -> list[Column]:
        """The columns that carry at least one value, in the book's order."""
        filled = {index for row in self.rows for index in row.values}
        return [c for c in self.columns if c.index in filled]


def borrow_dates(book: Book, siblings: list[Book]) -> None:
    """Undated columns take the dates of a sibling book in the same area whose
    month labels run the same way. Book 029 (3er grupo de secadores) wrote line
    speeds where the dates go; 028, its neighbour, has the same twelve
    labels, dated."""
    missing = [c for c in book.measured_columns() if c.day is None]
    if not missing:
        return
    labels = [plain(c.take) for c in book.measured_columns()]
    for sibling in siblings:
        if sibling is book or sibling.area != book.area:
            continue
        dated = [c for c in sibling.measured_columns() if c.day is not None]
        if [plain(c.take) for c in dated] != labels:
            continue
        for mine, theirs in zip(book.measured_columns(), dated, strict=True):
            if mine.day is None:
                mine.day, mine.source = theirs.day, f"fecha de {sibling.filename}"
        book.warnings.append(
            f"{len(missing)} columnas sin fecha: tomadas de {sibling.filename} (mismas etiquetas de mes)"
        )
        return
