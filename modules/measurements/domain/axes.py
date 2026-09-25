"""The order an analyst reads the axes of a point in: horizontal, vertical,
axial. Alphabetical order printed A, H, V everywhere it was used."""

from __future__ import annotations

_RANK = {"H": 0, "V": 1, "A": 2}


def axis_rank(axis: str) -> int:
    return _RANK.get(axis, len(_RANK))
