"""Internal asset code.

`asset_code` is mandatory and always unique inside a company; `client_tag` is
optional, free text and may repeat — the source data proves it does, carrying
`MB1141001B` on both the motor and the pump of EB 228.

Mandatory rather than optional because every reading, photo, report and audit
row points at it. A nullable key means the day a customer ships equipment with
no TAG, half the system has nothing to hold on to. It is auto-generated when
nobody types one, so in practice the user never has to care.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

_SEPARATORS = re.compile(r"[^A-Z0-9]+")

TYPE_ABBREVIATIONS = {
    "motor": "MOT",
    "pump": "BBA",
    "compressor": "CMP",
    "gearbox": "RED",
    "fan": "VEN",
    "blower": "SOP",
    "bearing_housing": "CHU",
    "other": "EQP",
}


def normalise(value: str) -> str:
    stripped = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return _SEPARATORS.sub("-", stripped.upper()).strip("-")


def generate(
    *,
    area_code: str,
    equipment_type: str,
    client_tag: str | None,
    taken: Iterable[str],
) -> str:
    """Prefer the customer's TAG when it is free; fall back to a positional
    code. Keeping the TAG as the code where possible is what makes the field
    crew recognise the equipment they already know."""
    used = {code.upper() for code in taken}

    if client_tag:
        candidate = normalise(client_tag)
        if candidate and candidate not in used:
            return candidate

    stem = f"{normalise(area_code)}-{TYPE_ABBREVIATIONS.get(equipment_type, 'EQP')}"
    for sequence in range(1, 10_000):
        candidate = f"{stem}-{sequence:03d}"
        if candidate not in used:
            return candidate
    raise ValueError(f"exhausted asset codes for {stem}")
