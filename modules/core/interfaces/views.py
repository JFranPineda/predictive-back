from __future__ import annotations

from dataclasses import asdict

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.core.application.module_installer import ModuleInstaller
from modules.core.domain.errors import DomainError
from modules.core.infrastructure.bus import bus
from modules.core.infrastructure.discovery import DjangoManifestSource
from modules.core.infrastructure.permissions_sync import (
    DjangoPermissionSynchronizer,
    ImportlibLifecycleHooks,
    YamlFixtureLoader,
)
from modules.core.infrastructure.repositories import DjangoModuleStateRepository
from modules.core.interfaces.serializers import ModuleInfoSerializer


def build_installer() -> ModuleInstaller:
    return ModuleInstaller(
        manifests=DjangoManifestSource(),
        states=DjangoModuleStateRepository(),
        permissions=DjangoPermissionSynchronizer(),
        fixtures=YamlFixtureLoader(),
        events=bus,
        hooks=ImportlibLifecycleHooks(),
    )


class ModuleViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]
    lookup_field = "code"

    def list(self, request):
        infos = build_installer().catalog()
        return Response([ModuleInfoSerializer.from_info(i) for i in infos])

    @action(detail=True, methods=["post"])
    def install(self, request, code: str):
        return self._run(request, lambda inst: asdict(inst.install(code)))

    @action(detail=True, methods=["post"])
    def uninstall(self, request, code: str):
        return self._run(request, lambda inst: inst.uninstall(code) or {"uninstalled": code})

    @action(detail=True, methods=["post"])
    def upgrade(self, request, code: str):
        return self._run(request, lambda inst: inst.upgrade(code) or {"upgraded": code})

    def _run(self, request, fn):
        # Installing or removing a module changes what everyone can do: it
        # was open to anyone signed in, a technician included.
        from rest_framework.exceptions import PermissionDenied

        from modules.security.infrastructure.access import build_actor

        if not build_actor(request.user, request.company_id).has("core.manage_modules"):
            raise PermissionDenied("Falta el permiso core.manage_modules")
        try:
            return Response(fn(build_installer()))
        except DomainError as exc:
            return Response(
                {"type": exc.code, "title": _explain(exc), "status": 409},
                status=status.HTTP_409_CONFLICT,
            )


def _explain(exc: DomainError) -> str:
    """The refusal in the words of the Aplicaciones screen: module names, not
    codes, and what to do about it."""
    from modules.core.domain.errors import ModuleInUse
    from modules.core.infrastructure.discovery import discover_manifests

    names = {manifest.code: manifest.name for manifest in discover_manifests()}
    if isinstance(exc, ModuleInUse):
        module = names.get(exc.module_code, exc.module_code)
        if exc.blockers == ("core module",):
            return f"«{module}» es parte del núcleo del sistema y no se puede desinstalar."
        blockers = ", ".join(f"«{names.get(code, code)}»" for code in exc.blockers)
        return f"No se puede desinstalar «{module}»: lo necesitan {blockers}. Desinstálalos primero."
    return str(exc)


class BootstrapView(APIView):
    """One call builds the whole frontend: identity, permissions, active
    modules and the menu they contribute."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from modules.security.infrastructure.access import permissions_for, visible_companies

        infos = [i for i in build_installer().catalog() if i.state == "installed"]
        granted = permissions_for(request.user, request.company_id)
        menu = [
            asdict(item)
            for info in infos
            for item in info.manifest.menu
            if item.permission is None or item.permission in granted
        ]
        return Response(
            {
                "user": {
                    "id": request.user.id,
                    "email": request.user.email,
                    "name": request.user.get_full_name(),
                    "initials": getattr(request.user, "initials", ""),
                },
                "company_id": request.company_id,
                "companies": visible_companies(request.user),
                "permissions": sorted(granted),
                "modules": [ModuleInfoSerializer.from_info(i) for i in infos],
                "menu": sorted(menu, key=lambda m: (m["parent"] or "", m["order"])),
            }
        )
