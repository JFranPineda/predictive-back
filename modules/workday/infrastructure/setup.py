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

# Q18: the chief engineer opens, closes and reopens the day and signs the
# close of each service. Created with what the company's engineer already
# holds, plus the day's permissions; Usuarios y permisos edits it after.
CHIEF_ENGINEER = {
    "code": "ingeniero_jefe",
    "name": "Ingeniero jefe",
    "base_role": "engineer",
    "description": "Abre, cierra y reabre la jornada y firma con su clave el cierre de cada servicio.",
    "permissions": (
        "workday.view", "workday.view_permits", "workday.manage", "workday.reopen",
        "workday.close_service", "workday.register_permit",
    ),
}

# By the behaviour a role borrows, not its name: companies name them freely.
GRANTS = {
    "technician": ("workday.view", "workday.register_permit"),
    "external_inspector": ("workday.view", "workday.register_permit"),
    "engineer": ("workday.view", "workday.view_permits"),
    "planner": ("workday.view", "workday.view_permits"),
}


# Q18: who opens and closes the day also reopens it and closes its services.
# Handed out only to a role holding none of them yet, like GRANTS.
WITH_MANAGE = ("workday.reopen", "workday.close_service")


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

        chief, created = Role.objects.get_or_create(
            company=company, code=CHIEF_ENGINEER["code"],
            defaults={"name": CHIEF_ENGINEER["name"], "base_role": CHIEF_ENGINEER["base_role"],
                      "description": CHIEF_ENGINEER["description"]},
        )
        if created:
            engineer = Role.objects.filter(company=company, code="engineer").first()
            if engineer is not None:
                chief.permissions.set(engineer.permissions.all())
            chief.permissions.add(*[permissions[c] for c in CHIEF_ENGINEER["permissions"] if c in permissions])

        for row in Role.objects.filter(company=company, permissions__code="workday.manage"):
            if not row.permissions.filter(code__in=WITH_MANAGE).exists():
                row.permissions.add(*[permissions[c] for c in WITH_MANAGE if c in permissions])

        for row in Role.objects.filter(company=company).exclude(code=SAFETY_CHIEF["code"]):
            behaviour = row.base_role or row.code
            codes = GRANTS.get(behaviour)
            if not codes or row.permissions.filter(module_code="workday").exists():
                continue
            row.permissions.add(*[permissions[c] for c in codes if c in permissions])


def _modules_of() -> set[str]:
    return {code.split(".")[0] for code in SAFETY_CHIEF["permissions"]} | {"workday"}
