"""What a round reads on each point of one machine (V3-11)."""

from __future__ import annotations

from modules.measurements.domain.point_magnitudes import magnitudes_for
from modules.measurements.infrastructure.models import Magnitude


def magnitude_plan(equipment, technique) -> list[tuple[object, Magnitude]]:
    """(point, magnitude) pairs to read, in point order.

    Opt-in magnitudes follow the kind's template point by point; the others
    are read on every active point, as they always were.
    """
    magnitudes = list(
        Magnitude.objects.filter(technique=technique)
        .select_related("default_unit")
        .order_by("display_order", "code")
    )
    opt_in = {magnitude.code for magnitude in magnitudes if magnitude.template_only}
    asked: dict[tuple[int, str], set[str]] = {}
    kind = equipment.asset_group.kind
    if kind is not None and opt_in:
        for row in kind.point_templates.all():
            asked.setdefault((row.number, row.axis), set()).update(row.magnitudes)

    by_code = {magnitude.code: magnitude for magnitude in magnitudes}
    codes = [magnitude.code for magnitude in magnitudes]
    return [
        (point, by_code[code])
        for point in equipment.points.filter(is_active=True).order_by("number", "axis")
        for code in magnitudes_for(codes, opt_in, asked.get((point.number, point.axis)))
    ]
