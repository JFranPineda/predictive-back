"""What installing `workday` adds to every company of the tenant.

The safety chief's profile (F3-06), and the day's permissions for the people
who work it. Idempotent, because an upgrade runs it again: a role is only
handed workday permissions if it holds none yet, so an administrator who
takes one away keeps that choice.
"""

from __future__ import annotations

SAFETY_CHIEF = {
    "code": "jefe_seguridad",
    "name": "Jefe de Seguridad",
    # Reads everything the day produced and alters none of it.
    "base_role": "client_viewer",
    "description": "Ve las jornadas, los ATS y los trabajos del día, sin poder modificarlos.",
    "permissions": (
        "workday.view", "workday.view_permits", "assets.view_equipment", "services.view",
        "summaries.view", "media.view",
    ),
}

# By the behaviour a role borrows, not its name: companies name them freely.
GRANTS = {
    "technician": ("workday.view", "workday.register_permit"),
    "external_inspector": ("workday.view", "workday.register_permit"),
    "engineer": ("workday.view", "workday.view_permits"),
    "planner": ("workday.view", "workday.view_permits"),
}


def install() -> None:
    from modules.core.models import Company
    from modules.security.models import Permission, Role

    permissions = {p.code: p for p in Permission.objects.filter(module_code__in=_modules_of())}
    for company in Company.objects.all():
        role, created = Role.objects.get_or_create(
            company=company, code=SAFETY_CHIEF["code"],
            defaults={"name": SAFETY_CHIEF["name"], "base_role": SAFETY_CHIEF["base_role"],
                      "description": SAFETY_CHIEF["description"]},
        )
        if created:
            role.permissions.set([permissions[c] for c in SAFETY_CHIEF["permissions"] if c in permissions])

        for row in Role.objects.filter(company=company).exclude(code=SAFETY_CHIEF["code"]):
            behaviour = row.base_role or row.code
            codes = GRANTS.get(behaviour)
            if not codes or row.permissions.filter(module_code="workday").exists():
                continue
            row.permissions.add(*[permissions[c] for c in codes if c in permissions])


def _modules_of() -> set[str]:
    return {code.split(".")[0] for code in SAFETY_CHIEF["permissions"]} | {"workday"}
