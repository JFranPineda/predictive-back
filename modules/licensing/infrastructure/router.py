"""Two planes, one process.

`default` is ours: the tenant registry and the licences, and nothing else.
Everything a customer owns lives in their own database, reached through the
alias the request put in context.

Fail closed: if no tenant is resolved, the router raises rather than quietly
writing maintenance data into the control plane.
"""

from __future__ import annotations

from .context import CONTROL_ALIAS, current_alias, current_tenant

CONTROL_PLANE_APPS = frozenset({"licensing"})


class TenantRouter:
    def db_for_read(self, model, **hints):
        return self._route(model._meta.app_label)

    def db_for_write(self, model, **hints):
        return self._route(model._meta.app_label)

    def allow_relation(self, obj1, obj2, **hints):
        # Relations are allowed inside one plane only. There are no foreign
        # keys between the control plane and a customer database by design.
        return self._plane(obj1) == self._plane(obj2)

    def allow_migrate(self, db, app_label, **hints):
        control = app_label in CONTROL_PLANE_APPS
        return control if db == CONTROL_ALIAS else not control

    def _route(self, app_label: str) -> str:
        if app_label in CONTROL_PLANE_APPS:
            return CONTROL_ALIAS
        return current_alias()

    @staticmethod
    def _plane(obj) -> str:
        return (
            CONTROL_ALIAS
            if obj._meta.app_label in CONTROL_PLANE_APPS
            else (current_tenant() or "?")
        )
