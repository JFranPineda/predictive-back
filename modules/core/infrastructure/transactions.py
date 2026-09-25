"""A transaction on the customer's database.

`transaction.atomic` without an alias opens the transaction on `default`,
which here is our control plane. A view decorated with it wrote the tenant's
rows outside any transaction: a save rejected halfway kept its first half (a
kind's components changed while its template was refused).
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps

from django.db import transaction

from modules.licensing.infrastructure.context import current_alias


def tenant_atomic[**P, R](function: Callable[P, R]) -> Callable[P, R]:
    """Runs the function in a transaction on the current tenant's database.
    The alias is resolved per call, since the tenant is per request."""

    @wraps(function)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        with transaction.atomic(using=current_alias()):
            return function(*args, **kwargs)

    return wrapper
