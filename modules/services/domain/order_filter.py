"""What the service ledger is being asked for.

The search box and the totals above the table read the same filter, so the
numbers on top always describe the rows underneath.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class OrderFilter:
    text: str = ""
    technique: str = ""
    status: str = ""
    date_from: date | None = None
    date_to: date | None = None


def order_filter_from(params: Mapping[str, str]) -> OrderFilter:
    """Unparseable dates are ignored rather than rejected: a half-typed date in
    the URL should not blank the ledger."""
    return OrderFilter(
        text=(params.get("q") or "").strip(),
        technique=(params.get("technique") or "").strip(),
        status=(params.get("status") or "").strip(),
        date_from=_date(params.get("from")),
        date_to=_date(params.get("to")),
    )


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None
