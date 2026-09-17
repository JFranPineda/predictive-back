from __future__ import annotations

from modules.core.domain.manifest import Manifest


class DjangoPermissionSynchronizer:
    """Module manifests are the only place permissions are declared."""

    def sync(self, module: Manifest) -> None:
        from modules.security.infrastructure.models import Permission

        for code, description in module.permissions:
            Permission.objects.update_or_create(
                code=code,
                defaults={"module_code": module.code, "description": description},
            )

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
