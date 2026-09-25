"""Which magnitudes a point is read on in a round (V3-11).

Most magnitudes of a service are read wherever the service goes, as before.
Some are opt-in (`template_only`): the global acceleration in g is measured
only on the trains whose kind asks for it, point by point. Without this, adding
acceleration to the catalogue would have added an empty "not measured" cell to
every point of every round — and every coverage figure would have dropped.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence


def magnitudes_for(
    service_magnitudes: Sequence[str],
    template_only: Iterable[str],
    template_row: Iterable[str] | None,
) -> list[str]:
    """The magnitudes one point is read on.

    `template_row` is what the kind's template says for this point (number and
    axis), or None when the kind has no row for it.
    """
    opt_in = set(template_only)
    asked = set(template_row or ())
    return [code for code in service_magnitudes if code not in opt_in or code in asked]
