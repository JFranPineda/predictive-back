"""Finds the tenant for a request and makes its database reachable."""

from __future__ import annotations

from dataclasses import dataclass

from modules.licensing.infrastructure.context import database_url_from_env, register_connection


class UnknownTenant(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ResolvedTenant:
    code: str
    name: str
    alias: str
    deployment: str
    is_suspended: bool
    suspended_reason: str


def resolve(code: str) -> ResolvedTenant:
    """Env var first, registry second.

    The env var wins so the first tenant can exist before the control plane has
    a row for it, and so a customer who refuses to hand over their database
    credentials can keep them in our deployment config instead of our database.
    """
    from modules.licensing.infrastructure.models import Tenant

    url = database_url_from_env(code)
    record = Tenant.objects.filter(code=code).first()
    if record is None and url is None:
        raise UnknownTenant(code)

    database_url = url or (record.database_url if record else "")
    if not database_url:
        raise UnknownTenant(f"{code} has no database configured")

    alias = register_connection(code, database_url)
    return ResolvedTenant(
        code=code,
        name=record.name if record else code,
        alias=alias,
        deployment=record.deployment if record else "hosted",
        is_suspended=bool(record and record.is_suspended),
        suspended_reason=record.suspended_reason if record else "",
    )


def tenant_from_host(host: str, base_domain: str) -> str | None:
    """`ambev.predictive.app` -> `ambev`. One customer, one subdomain, and no
    way to reach another customer's data by editing a payload."""
    host = host.split(":")[0].lower()
    if not base_domain or not host.endswith(base_domain) or host == base_domain:
        return None
    label = host[: -len(base_domain)].rstrip(".")
    return label.split(".")[-1] or None

