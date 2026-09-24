"""The access matrix of the plant, as the customer drew it.

Four profiles, and the line that matters runs between the first three and the
fourth: management reads the plant and cannot alter a single field value; the
technician writes, but only the visits he is on and only while they are open.
That line is drawn by each profile's behaviour, not only by its permissions,
so a permission ticked by mistake on a manager still cannot rewrite a reading.

    manage.py tenants run ambev seed_profiles
    manage.py tenants run ambev seed_profiles --demo-users   # one person each

Idempotent: it updates the profiles to this definition every time it runs.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from modules.core.models import Company
from modules.security.models import Membership, Permission, Role, User

READ_THE_PLANT = (
    "summaries.view", "summaries.export",
    "assets.view_equipment", "measurements.view_reading",
    "services.view", "reports.view", "thresholds.view_set",
)

PROFILES = {
    "gerente_general": {
        "name": "Gerente General",
        "base": "client_viewer",
        "description": "Monitoreo de KPIs de confiabilidad global y disponibilidad de planta.",
        "permissions": READ_THE_PLANT,
    },
    "subgerente_planta": {
        "name": "Subgerente de Planta",
        "base": "client_viewer",
        "description": (
            "Supervisión del cumplimiento del plan de mantenimiento y estado de "
            "activos críticos."
        ),
        "permissions": READ_THE_PLANT + (
            "services.view_authorship", "diagnostics.view",
        ),
    },
    "jefe_mantenimiento": {
        "name": "Jefe de Mantenimiento",
        # Planner behaviour: it can move the plan, never a field value.
        "base": "planner",
        "description": (
            "Control de alarmas generadas por predictivo, revisión del backlog de "
            "los técnicos y reprogramaciones."
        ),
        "permissions": READ_THE_PLANT + (
            "services.view_authorship", "diagnostics.view",
            "core.view_audit", "security.view_user",
            # Rescheduling an order changes the plan, not what was measured.
            "services.manage_order",
            "vibration.view", "thermography.view", "ultrasound.view",
            "media.view", "nameplate.view", "operating_data.view",
        ),
    },
    "tecnico_campo": {
        "name": "Personal Técnico",
        "base": "technician",
        "description": (
            "Carga de actividades ejecutadas: cambio de rodamientos, reportes de "
            "alineación láser, lecturas de vibraciones. Tres relevos de 8 horas."
        ),
        "permissions": (
            "summaries.view", "assets.view_equipment", "nameplate.view",
            "services.view",
            "measurements.view_reading", "measurements.add_reading",
            "vibration.view", "vibration.add_reading",
            "thermography.view", "thermography.add_reading",
            "ultrasound.view", "ultrasound.add_reading",
            "media.view", "media.upload",
            "diagnostics.view", "diagnostics.add_entry",
            "operating_data.view", "operating_data.add",
        ),
    },
}

DEMO_USERS = (
    ("gerencia@ambev.com.pe", "Rosa", "Medina", "RM", "gerente_general", ""),
    ("subgerencia@ambev.com.pe", "Luis", "Pariona", "LP", "subgerente_planta", ""),
    ("jefe.mtto@ambev.com.pe", "Ana", "Quispe", "AQ", "jefe_mantenimiento", ""),
)


class Command(BaseCommand):
    help = "Creates the plant's four access profiles"

    def add_arguments(self, parser) -> None:
        parser.add_argument("--demo-users", action="store_true")
        parser.add_argument("--password", default="predictive2026")

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        company = Company.objects.first()
        if company is None:
            self.stderr.write("No hay empresa")
            return

        known = set(Permission.objects.filter(is_active=True).values_list("code", flat=True))
        for code, spec in PROFILES.items():
            missing = sorted(set(spec["permissions"]) - known)
            if missing:
                # A profile silently missing a permission is worse than one
                # that fails loudly: the gap only shows up as a blank screen.
                raise SystemExit(f"{code}: permisos inexistentes {missing}")
            role, _ = Role.objects.update_or_create(
                company=company, code=code,
                defaults={
                    "name": spec["name"],
                    "base_role": spec["base"],
                    "description": spec["description"],
                },
            )
            role.permissions.set(Permission.objects.filter(code__in=spec["permissions"]))
            self.stdout.write(f"{spec['name']:24} {len(spec['permissions']):2} permisos · base {spec['base']}")

        if options["demo_users"]:
            self._demo_users(company, options["password"])

    def _demo_users(self, company, password: str) -> None:
        for email, first, last, initials, role_code, shift in DEMO_USERS:
            user = User.objects.filter(email=email).first()
            if user is None:
                user = User.objects.create_user(
                    email=email, password=password, first_name=first,
                    last_name=last, initials=initials,
                )
            role = Role.objects.get(company=company, code=role_code)
            Membership.objects.update_or_create(
                user=user, company=company,
                defaults={"role": role, "is_default": True, "shift": shift},
            )
            self.stdout.write(f"  {email:28} -> {role.name}")

        # The seeded technician moves onto the field profile and gets a shift.
        technician = User.objects.filter(email="jorge.a@simiai.pe").first()
        if technician:
            Membership.objects.filter(user=technician, company=company).update(
                role=Role.objects.get(company=company, code="tecnico_campo"), shift="A"
            )
            self.stdout.write("  jorge.a@simiai.pe            -> Personal Técnico · Turno A")
