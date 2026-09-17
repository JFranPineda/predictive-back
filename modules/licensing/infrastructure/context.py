"""Which customer database the current thread is talking to.

A request sets it once; everything downstream — ORM, Celery task, management
command — reads it. Nothing anywhere else decides a connection.
"""

from __future__ import annotations

import contextvars
import os
from contextlib import contextmanager

from django.conf import settings
from django.db import connections

from modules.core.domain.database_url import parse

CONTROL_ALIAS = "default"

_current_tenant: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_tenant", default=None
)


class TenantNotResolved(RuntimeError):
    """Raised instead of silently falling back to somebody else's database."""


def alias_for(code: str) -> str:
    return f"tenant_{code}"


def set_current_tenant(code: str | None) -> None:
    _current_tenant.set(code)


def current_tenant() -> str | None:
    return _current_tenant.get() or os.environ.get("TENANT") or getattr(
        settings, "DEFAULT_TENANT", None
    )


def current_alias() -> str:
    code = current_tenant()
    if not code:
        raise TenantNotResolved(
            "No tenant in context: set X-Tenant, DEFAULT_TENANT or use use_tenant()"
        )
    return ensure_registered(code)


def ensure_registered(code: str) -> str:
    """Makes a tenant's connection usable, registering it on first touch.

    Env var first so a deployment can run before the control plane has a row —
    and so a customer who will not put their credentials in our database can
    keep them in the process environment instead.
    """
    alias = alias_for(code)
    if alias in connections.databases:
        return alias

    url = database_url_from_env(code)
    if url is None:
        url = _url_from_registry(code)
    if not url:
        raise TenantNotResolved(f"tenant '{code}' has no database configured")
    return register_connection(code, url)


def _url_from_registry(code: str) -> str | None:
    from django.db import DatabaseError

    try:
        from modules.licensing.infrastructure.models import Tenant

        return Tenant.objects.using(CONTROL_ALIAS).filter(code=code).values_list(
            "database_url", flat=True
        ).first()
    except (DatabaseError, LookupError):
        # First boot: the control plane has not been migrated yet.
        return None


@contextmanager
def use_tenant(code: str):
    token = _current_tenant.set(code)
    try:
        yield alias_for(code)
    finally:
        _current_tenant.reset(token)


def register_connection(code: str, database_url: str) -> str:
    """Adds a customer database to the live connection map.

    Django reads `connections.databases` lazily, so a tenant added today is
    reachable without a restart — which is the whole point of keeping the
    registry in a table instead of in `settings.py`.
    """
    alias = alias_for(code)
    if alias in connections.databases:
        return alias
    config = parse(database_url, conn_max_age=getattr(settings, "TENANT_CONN_MAX_AGE", 60))
    connections.databases[alias] = config.as_django()
    return alias


def database_url_from_env(code: str) -> str | None:
    """`TENANT_AMBEV_DATABASE_URL`. This is how the first tenant is bootstrapped
    before the control-plane table exists, and how a customer's credentials can
    stay out of our database entirely if they prefer."""
    return os.environ.get(f"TENANT_{code.upper().replace('-', '_')}_DATABASE_URL")
