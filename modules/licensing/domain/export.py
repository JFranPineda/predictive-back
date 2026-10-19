"""The full export (v4 Phase 4): everything the customer owns, in formats any
tool opens, whatever the state of the licence. This is the exit guarantee of
the contract, made code.

Two things never travel: password hashes (a file that goes by email or USB
must not carry them; a user restored from it sets a new password) and
sessions. Everything else does, untouched.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from typing import Any

# One header row, then data: Excel's 1,048,576 rows per sheet.
EXCEL_MAX_ROWS = 1_048_575
MAX_SHEET_NAME = 31

EXCLUDED_TABLES = frozenset({
    "django_session",
    "token_blacklist_outstandingtoken",
    "token_blacklist_blacklistedtoken",
})
# Django reads a password starting with "!" as unusable.
REDACTED_COLUMNS: dict[tuple[str, str], str] = {
    ("security_user", "password"): "!exportado-sin-contraseña",
}


def sheet_name(table: str, part: int, used: set[str]) -> str:
    """Excel caps sheet names at 31 characters and wants them unique; a table
    split across sheets says which part each one is."""
    suffix = f" ({part})" if part > 1 else ""
    base = table[: MAX_SHEET_NAME - len(suffix)] + suffix
    name, counter = base, 2
    while name in used:
        tail = f"~{counter}{suffix}"
        name = table[: MAX_SHEET_NAME - len(tail)] + tail
        counter += 1
    used.add(name)
    return name


def split_rows(rows: Iterator[Any], limit: int) -> Iterator[list[Any]]:
    """Chunks of at most `limit` rows; an empty table yields one empty chunk,
    so it still gets its sheet."""
    chunk: list[Any] = []
    emitted = False
    for row in rows:
        chunk.append(row)
        if len(chunk) == limit:
            yield chunk
            chunk, emitted = [], True
    if chunk or not emitted:
        yield chunk


def redact(table: str, columns: Sequence[str], row: Iterable[Any]) -> tuple[Any, ...]:
    return tuple(
        REDACTED_COLUMNS.get((table, column), value) for column, value in zip(columns, row, strict=True)
    )
