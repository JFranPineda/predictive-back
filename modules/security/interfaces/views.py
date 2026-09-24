from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.security.models import Membership


class UserListView(APIView):
    """Who has access, with what role and over which areas.

    External inspectors are flagged: the difference between staff and a
    contractor is the first thing an administrator needs to see.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        memberships = (
            Membership.objects.filter(company_id=request.company_id)
            .select_related("user", "role")
            .prefetch_related("restrictions", "role__permissions")
            .order_by("user__first_name", "user__last_name")
        )
        return Response([_member_payload(membership) for membership in memberships])


def _member_payload(membership) -> dict:
    """One person, with everything an administrator has to be able to see.

    The list used to show a role name and nothing behind it, so answering
    "what can Jorge actually do?" meant reading the role screen and guessing.
    The effective permissions travel with the person now.
    """
    from modules.security.domain.actor import behaviour_of

    role = membership.role
    return {
        "id": membership.user_id,
        "email": membership.user.email,
        "full_name": membership.user.get_full_name(),
        "initials": membership.user.initials,
        "role": role.code,
        "role_name": role.name,
        "base_role": behaviour_of(role.base_role or role.code).value,
        "shift": membership.shift,
        "has_access_code": bool(membership.user.access_code_digest),
        "access_code_set_at": membership.user.access_code_set_at,
        "is_external": membership.user.is_external,
        "is_active": membership.user.is_active,
        "language": membership.user.language or "",
        "permissions": sorted(p.code for p in role.permissions.all() if p.is_active),
        "area_restrictions": [
            ref for restriction in membership.restrictions.all()
            for ref in restriction.refs
        ],
    }


class UserCreateView(APIView):
    """Invites somebody into this company.

    The password is set once here and the person changes it; we do not email
    credentials, because a password in an inbox is a password in the clear
    forever.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        from rest_framework.exceptions import PermissionDenied

        from modules.security.application.access import build_actor
        from modules.security.domain.actor import Role
        from modules.security.infrastructure.models import Role as RoleModel, User

        actor = build_actor(request.user, request.company_id)
        if not actor.has("security.manage_user"):
            raise PermissionDenied("No puedes administrar usuarios")

        email = (request.data.get("email") or "").strip().lower()
        role_code = request.data.get("role")
        password = request.data.get("password") or ""
        if not email or "@" not in email:
            return Response({"type": "invalid_email", "title": "Correo no válido", "status": 400},
                            status=400)
        if len(password) < 10:
            return Response(
                {"type": "weak_password", "title": "La contraseña necesita 10 caracteres o más",
                 "status": 400},
                status=400,
            )

        role = RoleModel.objects.filter(company_id=request.company_id, code=role_code).first()
        if role is None:
            return Response({"type": "unknown_role", "title": "Rol desconocido", "status": 400},
                            status=400)

        # External is a behaviour, not a name: a company's "Contratista" built
        # on external_inspector is external too.
        is_external = (role.base_role or role.code) == Role.EXTERNAL_INSPECTOR.value
        user = User.objects.filter(email=email).first()
        if user is None:
            user = User.objects.create_user(
                email=email,
                password=password,
                first_name=(request.data.get("first_name") or "").strip(),
                last_name=(request.data.get("last_name") or "").strip(),
                initials=(request.data.get("initials") or "").strip()[:6],
                is_external=is_external,
            )
        elif Membership.objects.filter(user=user, company_id=request.company_id).exists():
            return Response(
                {"type": "already_member", "title": "Esa persona ya pertenece a la compañía",
                 "status": 409},
                status=409,
            )

        membership = Membership.objects.create(
            user=user, company_id=request.company_id, role=role, is_default=True,
            shift=_shift(request.data.get("shift")),
        )
        from modules.core.infrastructure.audit import record

        record(request, "user.invited", object_type="user", object_id=user.id,
               after={"email": user.email, "role": role.code, "shift": membership.shift})
        return Response({
            "id": user.id, "email": user.email, "full_name": user.get_full_name(),
            "initials": user.initials, "role": role.code, "role_name": role.name,
            "is_external": user.is_external, "is_active": user.is_active,
            "language": user.language or "", "area_restrictions": [],
        }, status=201)


class UserDetailView(APIView):
    """Role and activation. Everything else about a person — their name, their
    password — is theirs to change, not an administrator's."""

    permission_classes = [IsAuthenticated]

    def patch(self, request, user_id: int):
        from rest_framework.exceptions import PermissionDenied

        from modules.security.application.access import build_actor
        from modules.security.domain.actor import Role
        from modules.security.infrastructure.models import Role as RoleModel

        actor = build_actor(request.user, request.company_id)
        if not actor.has("security.manage_user"):
            raise PermissionDenied("No puedes administrar usuarios")

        membership = (
            Membership.objects.filter(company_id=request.company_id, user_id=user_id)
            .select_related("user", "role")
            .first()
        )
        if membership is None:
            return Response({"type": "not_found", "status": 404}, status=404)

        from modules.core.infrastructure.audit import record

        before = {"role": membership.role.code, "shift": membership.shift,
                  "is_active": membership.user.is_active}

        role_code = request.data.get("role")
        if role_code:
            # Locking yourself out of your own company is the classic footgun.
            if membership.user_id == request.user.id and role_code != membership.role.code:
                raise PermissionDenied("No puedes cambiar tu propio rol")
            # Any role this company has — the check against the seven shipped
            # ones is what made every role the company created unassignable.
            role = RoleModel.objects.filter(company_id=request.company_id, code=role_code).first()
            if role is None:
                return Response({"type": "unknown_role", "status": 400}, status=400)
            membership.role = role
            membership.save(update_fields=["role"])
            membership.user.is_external = (
                (role.base_role or role.code) == Role.EXTERNAL_INSPECTOR.value
            )
            membership.user.save(update_fields=["is_external"])

        if "shift" in request.data:
            membership.shift = _shift(request.data.get("shift"))
            membership.save(update_fields=["shift"])

        if "is_active" in request.data:
            if membership.user_id == request.user.id:
                raise PermissionDenied("No puedes desactivarte a ti mismo")
            membership.user.is_active = bool(request.data["is_active"])
            membership.user.save(update_fields=["is_active"])

        after = {"role": membership.role.code, "shift": membership.shift,
                 "is_active": membership.user.is_active}
        if after != before:
            record(request, "user.access_changed", object_type="user",
                   object_id=membership.user_id, before=before, after=after)

        profile = {}
        for field in ("first_name", "last_name", "initials"):
            if field in request.data:
                profile[field] = (request.data.get(field) or "").strip()
        if profile:
            for field, value in profile.items():
                setattr(membership.user, field, value)
            membership.user.save(update_fields=list(profile))

        if "password" in request.data:
            password = request.data["password"] or ""
            if len(password) < 10:
                return Response(
                    {"type": "weak_password",
                     "title": "La contraseña necesita 10 caracteres o más", "status": 400},
                    status=400,
                )
            membership.user.set_password(password)
            membership.user.save(update_fields=["password"])

        if "area_restrictions" in request.data:
            _set_area_scope(membership, request.data["area_restrictions"])

        membership.refresh_from_db()
        return Response(_member_payload(membership))

    def delete(self, request, user_id: int):
        """Removes access to this company, not the person.

        Their name stays on every reading and conclusion they wrote; deleting
        the user would take the authorship of past reports with it.
        """
        from rest_framework.exceptions import PermissionDenied

        from modules.security.application.access import build_actor

        actor = build_actor(request.user, request.company_id)
        if not actor.has("security.manage_user"):
            raise PermissionDenied("No puedes administrar usuarios")
        if user_id == request.user.id:
            raise PermissionDenied("No puedes quitarte a ti mismo el acceso")

        membership = Membership.objects.filter(
            company_id=request.company_id, user_id=user_id
        ).first()
        if membership is None:
            return Response({"type": "not_found", "status": 404}, status=404)
        membership.delete()
        return Response(status=204)


def _set_area_scope(membership, refs) -> None:
    """An empty list means every area; a populated one narrows the user to
    exactly those. The distinction matters: `[]` must not read as "nothing"."""
    from modules.security.infrastructure.models import ScopeRestriction

    membership.restrictions.filter(scope="area").delete()
    cleaned = [int(ref) for ref in (refs or []) if str(ref).isdigit()]
    if cleaned:
        ScopeRestriction.objects.create(membership=membership, scope="area", refs=cleaned)


class MyLanguageView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request):
        from modules.core.domain.i18n import normalise_language

        language = normalise_language(request.data.get("language"))
        if language is None:
            return Response({"type": "unsupported_language", "status": 400}, status=400)
        request.user.language = language
        request.user.save(update_fields=["language"])
        return Response({"language": language})


def _shift(value) -> str:
    """One of the three 8-hour relays, or none."""
    value = (value or "").strip().upper()
    if value and value not in {"A", "B", "C"}:
        from rest_framework.exceptions import ValidationError

        raise ValidationError("El turno debe ser A, B o C")
    return value
