"""Client TAG parsing.

The customer encodes the equipment type in the TAG prefix (MB101001A = Motor of
Bomba 101001A). It is a useful hint for imports, never a source of truth: the
same TAG appears on both motor and pump in `TABLA DE TENDENCIAS.xls`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PREFIXES: tuple[tuple[str, str], ...] = (
    ("MSP", "motor"),   # motor soplador
    ("MB", "motor"),
    ("MC", "motor"),
    ("MR", "motor"),
    ("ME", "motor"),
    ("B", "pump"),
    ("C", "compressor"),
    ("R", "gearbox"),
    ("SP", "blower"),
    ("V", "fan"),
)

_TAG_IN_TEXT = re.compile(r"TAG\s*:\s*([A-Z0-9\-]+)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ParsedTag:
    raw: str
    guessed_type: str | None


def parse(tag: str) -> ParsedTag:
    clean = tag.strip().upper()
    for prefix, equipment_type in _PREFIXES:
        if clean.startswith(prefix):
            return ParsedTag(raw=clean, guessed_type=equipment_type)
    return ParsedTag(raw=clean, guessed_type=None)


def extract_from_cell(text: str) -> str | None:
    """Source cells look like 'MOTOR -\\nTAG:MB101001A'."""
    match = _TAG_IN_TEXT.search(text or "")
    return match.group(1).strip() if match else None


def split_area_label(label: str) -> tuple[str, str]:
    """'501 - PACKAGING CERVEZA' -> ('501', 'PACKAGING CERVEZA')."""
    cleaned = " ".join((label or "").split())
    if " - " in cleaned:
        code, _, name = cleaned.partition(" - ")
        return code.strip(), name.strip()
    head, _, tail = cleaned.partition(" ")
    return (head.strip(), tail.strip()) if tail else (cleaned, cleaned)
