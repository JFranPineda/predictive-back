from __future__ import annotations

from django.utils import timezone

from modules.core.domain.manifest import ModuleState
from modules.core.infrastructure.models import InstalledModule


class DjangoModuleStateRepository:
    def all_states(self) -> dict[str, tuple[ModuleState, str | None]]:
        return {
            row.code: (row.state, row.installed_version or None)
            for row in InstalledModule.objects.all()
        }

    def installed_codes(self) -> frozenset[str]:
        return frozenset(
            InstalledModule.objects.filter(state="installed").values_list("code", flat=True)
        )

    def set_state(self, code: str, state: ModuleState, version: str | None) -> None:
        InstalledModule.objects.update_or_create(
            code=code,
            defaults={
                "state": state,
                "installed_version": version or "",
                "installed_at": timezone.now() if state == "installed" else None,
            },
        )
