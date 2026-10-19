"""The two counts and the version that travel in a renewal request. Counts,
never names: what leaves the customer's network is how many, not which."""

from __future__ import annotations

import tomllib
from importlib.metadata import PackageNotFoundError, version

from django.conf import settings

from modules.licensing.infrastructure.context import use_tenant


def counts(tenant_code: str) -> tuple[int, int]:
    """Equipment in the plan across the tenant's companies, and active users."""
    from modules.assets.infrastructure.plan_counts import equipment_in_plan
    from modules.core.infrastructure.models import Company
    from modules.security.infrastructure.models import User

    with use_tenant(tenant_code):
        companies = Company.objects.values_list("id", flat=True)
        equipment = sum(equipment_in_plan(company_id) for company_id in companies)
        return equipment, User.objects.filter(is_active=True).count()


def program_version() -> str:
    """The installed package's, or pyproject's when running from a checkout
    without installing it, which is how every development machine runs."""
    try:
        return version("predictive-back")
    except PackageNotFoundError:
        pass
    try:
        with open(settings.BASE_DIR / "pyproject.toml", "rb") as handle:
            return tomllib.load(handle)["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "desconocida"
