""""Otros": a problem the catalogue does not name yet.

The closed list is what makes faults countable, so "Otros" is not a free pass:
it must say what was found, and those descriptions are what the catalogue
grows from. It belongs to the visit, not to the catalogue, so every technique
has it — including the ones added after this was written.
"""

from __future__ import annotations

MAX_LENGTH = 300


class OtherFaultWithoutDescriptionError(ValueError):
    def __init__(self) -> None:
        super().__init__("Describe el problema marcado como «Otros»")


def other_fault_text(marked: bool, description: str | None) -> str:
    """The text to keep: empty when "Otros" is not marked."""
    if not marked:
        return ""
    text = (description or "").strip()[:MAX_LENGTH]
    if not text:
        raise OtherFaultWithoutDescriptionError
    return text
