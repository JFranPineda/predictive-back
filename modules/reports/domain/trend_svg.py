"""Section VI of the report — the trend — drawn as SVG for the PDF.

The screen draws it with ECharts; a PDF has no JavaScript. One chart per
magnitude, one line per point, the same honest rule as the screen: a round
with no value is a gap the line steps over, never a zero.
"""

from __future__ import annotations

from html import escape

PALETTE = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948")


def trend_svg(
    dates: list[str],
    series: list[tuple[str, list[float | None]]],
    *,
    unit: str = "",
    width: int = 680,
    height: int = 220,
    end_labels: bool = True,
) -> str:
    left, right, top, bottom = 44, 70, 14, 34
    plot_w, plot_h = width - left - right, height - top - bottom
    values = [value for _, points in series for value in points if value is not None]
    if not dates or not values:
        return ""
    ceiling = _nice(max(values)) or 1.0

    def x(index: int) -> float:
        return left + (plot_w * index / (len(dates) - 1) if len(dates) > 1 else plot_w / 2)

    def y(value: float) -> float:
        return top + plot_h * (1 - value / ceiling)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="Helvetica, Arial, sans-serif" font-size="9">'
    ]
    for step in range(5):
        level = ceiling * step / 4
        parts.append(
            f'<line x1="{left}" x2="{left + plot_w}" y1="{y(level):.1f}" y2="{y(level):.1f}" '
            f'stroke="#e2e8f0"/><text x="{left - 4}" y="{y(level) + 3:.1f}" text-anchor="end" '
            f'fill="#64748b">{level:g}</text>'
        )
    parts.append(f'<text x="{left + 2}" y="{top - 4}" fill="#64748b">{escape(unit)}</text>')
    every = max(1, len(dates) // 8)
    for index, label in enumerate(dates):
        if index % every == 0 or index == len(dates) - 1:
            parts.append(
                f'<text x="{x(index):.1f}" y="{height - 16}" text-anchor="middle" '
                f'fill="#64748b">{escape(label)}</text>'
            )
    for number, (label, points) in enumerate(series):
        colour = PALETTE[number % len(PALETTE)]
        # Nulls are stepped over: the line joins the rounds that were measured.
        coords = [(x(i), y(v)) for i, v in enumerate(points) if v is not None]
        if not coords:
            continue
        joined = " ".join(f"{px:.1f},{py:.1f}" for px, py in coords)
        parts.append(f'<polyline fill="none" stroke="{colour}" stroke-width="1.6" points="{joined}"/>')
        parts.extend(
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="2.2" fill="{colour}"/>' for px, py in coords
        )
        if not end_labels:
            continue
        last_x, last_y = coords[-1]
        parts.append(
            f'<text x="{last_x + 5:.1f}" y="{last_y + 3:.1f}" fill="{colour}" '
            f'font-weight="bold">{escape(label)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _nice(value: float) -> float:
    """A round ceiling above the data: 4.3 → 5, 12.1 → 15, 0.86 → 1."""
    if value <= 0:
        return 0.0
    magnitude = 10 ** len(str(int(value))) / 10 if value >= 1 else 0.1
    for step in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if step * magnitude >= value:
            return step * magnitude
    return 10 * magnitude
