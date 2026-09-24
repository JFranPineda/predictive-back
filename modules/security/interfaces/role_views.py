"""Roles and what each one may do, editable from the UI.

Permissions are declared by module manifests and synced on install, so this
screen never invents them: it decides which of the declared permissions each
role holds. Grouping them by module is what makes a matrix of sixty checkboxes
readable.
"""

from __future__ import annotations

from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.security.application.access import build_actor
from modules.security.domain.actor import Role as RoleEnum
from modules.security.models import Membership, Permission, Role

# What a company-made role may borrow its behaviour from. Platform admin is
# ours, not the customer's to hand out.
BASES = (
    "company_admin", "engineer", "planner", "technician",
    "external_inspector", "client_viewer",
)

# The four things a user does to a record, as the request put it. Every
# permission code ends in one of these, or it is something else entirely
# (import, issue, recalculate) and shows up under "otros".
ACTIONS = {
    "view": ("view", "list"),
    "add": ("add", "create", "manage_"),
    "change": ("change", "edit", "update", "manage_"),
    "delete": ("delete", "remove"),
}


class RoleAdminView(APIView):
    permission_classes = [IsAuthenticated]

    def require(self, request) -> None:
        actor = build_actor(request.user, request.company_id)
        if not actor.has("security.manage_role"):
            raise PermissionDenied("Falta el permiso security.manage_role")

    def scoped(self, request):
        # System roles (company=None) are shared; a company edits its own copy.
        return Role.objects.filter(company_id=request.company_id)


class RoleListView(RoleAdminView):
    def get(self, request):
        language = getattr(request, "language", "es")
        del language
        roles = self.scoped(request).prefetch_related("permissions").order_by("name")
        modules: dict[str, list[dict]] = {}
        for permission in Permission.objects.filter(is_active=True).order_by("code"):
            modules.setdefault(permission.module_code, []).append({
                "code": permission.code,
                "description": permission.description,
                "action": _action_of(permission.code),
            })

        return Response({
            "roles": [
                {
                    "id": role.id,
                    "code": role.code,
                    "name": role.name,
                    "is_system": role.code in {r.value for r in RoleEnum},
                    "base_role": role.base_role or role.code,
                    "description": role.description,
                    "member_count": Membership.objects.filter(role=role).count(),
                    "permissions": sorted(p.code for p in role.permissions.all()),
                }
                for role in roles
            ],
            "modules": [
                {"code": code, "permissions": permissions}
                for code, permissions in sorted(modules.items())
            ],
        })

    def post(self, request):
        self.require(request)
        name = (request.data.get("name") or "").strip()
        if not name:
            raise ValidationError("El nombre es obligatorio")
        code = _slug(request.data.get("code") or name)
        if self.scoped(request).filter(code=code).exists():
            raise ValidationError(f"Ya existe un rol con el código '{code}'")

        role = Role.objects.create(
            company_id=request.company_id, code=code, name=name,
            base_role=_base(request.data.get("base_role")),
            description=(request.data.get("description") or "").strip()[:240],
        )
        _set_permissions(role, request.data.get("permissions"))
        from modules.core.infrastructure.audit import record

        record(request, "role.created", object_type="role", object_id=role.code,
               after={"base_role": role.base_role,
                      "permissions": sorted(p.code for p in role.permissions.all())})
        return Response({"id": role.id, "code": role.code, "name": role.name}, status=201)


class RoleDetailView(RoleAdminView):
    @transaction.atomic
    def patch(self, request, role_id: int):
        self.require(request)
        role = _get(self.scoped(request), role_id)
        if "name" in request.data:
            role.name = (request.data.get("name") or "").strip()
            role.save(update_fields=["name"])
        if "description" in request.data:
            role.description = (request.data.get("description") or "").strip()[:240]
            role.save(update_fields=["description"])
        if "base_role" in request.data:
            # A system role's behaviour is what the policies were written for;
            # repointing one would silently change every account built on it.
            if role.code in {r.value for r in RoleEnum}:
                raise ValidationError("El comportamiento de un rol del sistema no se cambia")
            role.base_role = _base(request.data["base_role"])
            role.save(update_fields=["base_role"])
        if "permissions" in request.data:
            _assert_not_locking_yourself_out(request, role, request.data["permissions"])
            before = sorted(p.code for p in role.permissions.all())
            _set_permissions(role, request.data["permissions"])
            after = sorted(p.code for p in role.permissions.all())
            if before != after:
                from modules.core.infrastructure.audit import record

                # Only the difference: sixty codes twice is a row nobody reads.
                record(request, "role.permissions_changed", object_type="role",
                       object_id=role.code,
                       before={"removed": sorted(set(before) - set(after))},
                       after={"added": sorted(set(after) - set(before))})
        return Response({
            "id": role.id,
            "code": role.code,
            "name": role.name,
            "permissions": sorted(p.code for p in role.permissions.all()),
        })

    def delete(self, request, role_id: int):
        self.require(request)
        role = _get(self.scoped(request), role_id)
        members = Membership.objects.filter(role=role).count()
        if members:
            raise ValidationError(f"El rol tiene {members} usuarios; muévelos antes de eliminarlo")
        if role.code in {r.value for r in RoleEnum}:
            raise ValidationError("Un rol del sistema no se elimina")
        role.delete()
        return Response(status=204)


def _assert_not_locking_yourself_out(request, role: Role, codes) -> None:
    """Removing your own ability to manage roles is a one-way door: nobody in
    the company could hand it back."""
    mine = Membership.objects.filter(user=request.user, company_id=request.company_id).first()
    if mine and mine.role_id == role.id and "security.manage_role" not in set(codes or []):
        raise ValidationError(
            "No puedes quitarte a ti mismo el permiso de administrar roles"
        )


def _set_permissions(role: Role, codes) -> None:
    if codes is None:
        return
    permissions = list(Permission.objects.filter(code__in=list(codes), is_active=True))
    unknown = set(codes) - {p.code for p in permissions}
    if unknown:
        raise ValidationError(f"Permisos desconocidos: {', '.join(sorted(unknown))}")
    role.permissions.set(permissions)


def _base(value) -> str:
    """Every company role must say how it behaves; the most restricted is the
    default, so forgetting to choose never grants write access."""
    value = (value or "client_viewer").strip()
    if value not in BASES:
        raise ValidationError(f"Comportamiento desconocido: {value}")
    return value


def _action_of(code: str) -> str:
    tail = code.split(".", 1)[-1]
    for action, prefixes in ACTIONS.items():
        if any(tail.startswith(prefix) for prefix in prefixes):
            return action
    return "other"


def _get(queryset, pk: int) -> Role:
    role = queryset.filter(id=pk).first()
    if role is None:
        raise ValidationError("Ese rol no existe")
    return role


def _slug(value: str) -> str:
    cleaned = "".join(c if c.isalnum() else "_" for c in (value or "").strip().lower())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "rol"
