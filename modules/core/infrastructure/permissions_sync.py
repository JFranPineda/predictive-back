from __future__ import annotations

from modules.core.domain.manifest import Manifest


class DjangoPermissionSynchronizer:
    """Module manifests are the only place permissions are declared."""

    def sync(self, module: Manifest) -> None:
        from django.db.models import Q

        from modules.security.infrastructure.models import Permission, Role

        created = []
        for code, description in module.permissions:
            permission, is_new = Permission.objects.update_or_create(
                code=code,
                defaults={"module_code": module.code, "description": description},
            )
            if is_new:
                created.append(permission)

        # The company administrator holds everything the installed modules
        # declare. It was seeded with every permission once, so a permission
        # declared later never reached it — nobody could then hand it out.
        # Granted only on creation: an administrator who unticks one later
        # keeps that choice on the next upgrade.
        if created:
            for role in Role.objects.filter(
                Q(code="company_admin") | Q(base_role="company_admin")
            ):
                role.permissions.add(*created)

    def revoke(self, module_code: str) -> None:
        from modules.security.infrastructure.models import Permission

        Permission.objects.filter(module_code=module_code).update(is_active=False)


class YamlFixtureLoader:
    """Loads `modules/<code>/fixtures/*.yaml` on install. Idempotent by design:
    reinstalling a module must not duplicate its catalogue rows."""

    def load(self, module: Manifest) -> None:
        if not module.fixtures:
            return
        from django.core.management import call_command

        for fixture in module.fixtures:
            call_command("loaddata", f"modules/{module.code}/fixtures/{fixture}", verbosity=0)
