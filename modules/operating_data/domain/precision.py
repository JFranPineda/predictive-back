"""How precisely an operating value is kept.

The customer reads operating data as whole numbers (1785 rpm, 46 A), so each
parameter declares its decimals and the value is rounded when it is written,
not only when it is shown — otherwise the report and the screen disagree.
The power factor is the exception: it lives between 0 and 1.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

POWER_FACTOR = "power_factor"
POWER_FACTOR_DECIMALS = 2


def to_precision(value: Decimal | None, decimals: int) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)


def decimals_for(code: str) -> int:
    """The precision a parameter gets by default."""
    return POWER_FACTOR_DECIMALS if code == POWER_FACTOR else 0
