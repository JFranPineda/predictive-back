"""Reading a spectrum the way an instrument exports it.

SEMAPI and SKF both write two columns — frequency and amplitude — under a
header of a few lines that nobody agrees on. Parsing is kept here, pure, so
the shapes each vendor produces can be pinned down without a database or a
file: the day a third instrument arrives, this is the only file that changes.
"""

from __future__ import annotations

from dataclasses import dataclass

# What the vendors call the two columns, lowercased.
FREQUENCY_HEADERS = ("frequency", "frecuencia", "freq", "hz", "orden", "order")
AMPLITUDE_HEADERS = ("amplitude", "amplitud", "amp", "magnitude", "value", "valor")


@dataclass(frozen=True)
class Curve:
    frequencies: list[float]
    amplitudes: list[float]
    unit: str = ""

    def __len__(self) -> int:
        return len(self.frequencies)

    @property
    def peak(self) -> tuple[float, float] | None:
        if not self.amplitudes:
            return None
        index = max(range(len(self.amplitudes)), key=self.amplitudes.__getitem__)
        return self.frequencies[index], self.amplitudes[index]

    @property
    def span(self) -> tuple[float, float] | None:
        if not self.frequencies:
            return None
        return min(self.frequencies), max(self.frequencies)

    def as_dict(self) -> dict:
        return {"freq": self.frequencies, "amp": self.amplitudes, "unit": self.unit}


class SpectrumFormatError(ValueError):
    """The file is not a two-column spectrum."""


def parse_csv(text: str) -> Curve:
    """Frequency/amplitude pairs out of whatever the instrument wrote.

    Header lines, blank lines and vendor preambles are skipped rather than
    rejected: a crew that has to clean a CSV by hand stops exporting it.
    """
    delimiter = _delimiter(text)
    frequencies: list[float] = []
    amplitudes: list[float] = []
    unit = ""
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.split(delimiter)]
        if len(cells) < 2:
            continue
        pair = _numbers(cells[0], cells[1])
        if pair is None:
            unit = unit or _unit_from_header(cells)
            continue
        frequencies.append(pair[0])
        amplitudes.append(pair[1])

    if len(frequencies) < 2:
        raise SpectrumFormatError(
            "El archivo no tiene pares frecuencia/amplitud reconocibles"
        )
    return Curve(frequencies, amplitudes, unit)


def _delimiter(text: str) -> str:
    """The separator that yields the most numeric pairs, not the most hits.

    Counting characters picks the comma out of `0,0;0,01` — a semicolon file
    with decimal commas — and every row then parses as one column.

    Unquoted thousands separators (`1,234.50,0.02`) stay ambiguous and are
    read as three columns. No instrument in the source set writes them; if one
    ever does, the header is what will have to disambiguate it.
    """
    sample = text.splitlines()[:60]
    return max(
        (";", "\t", ","),
        key=lambda candidate: sum(
            1
            for line in sample
            for cells in [line.split(candidate)]
            if len(cells) >= 2 and _numbers(cells[0], cells[1]) is not None
        ),
    )


def _numbers(first: str, second: str) -> tuple[float, float] | None:
    try:
        return float(_decimal(first)), float(_decimal(second))
    except ValueError:
        return None


def _decimal(cell: str) -> str:
    """`es-ES` instruments write `1.234,50`; `es-PE` writes `1,234.50`.

    The separator that appears last is the decimal one — assuming "Spanish
    means comma" is how a 1 234,5 Hz axis became 12 345 Hz.
    """
    cell = cell.strip().replace(" ", "")
    if "," in cell and "." in cell:
        if cell.rfind(",") > cell.rfind("."):
            return cell.replace(".", "").replace(",", ".")
        return cell.replace(",", "")
    if "," in cell:
        return cell.replace(",", ".")
    return cell


def _unit_from_header(cells: list[str]) -> str:
    for cell in cells:
        lowered = cell.lower()
        if any(name in lowered for name in AMPLITUDE_HEADERS):
            for candidate in ("mm/s", "mm/seg", "gs", "g", "um", "µm", "db"):
                if candidate in lowered:
                    return candidate
    return ""
