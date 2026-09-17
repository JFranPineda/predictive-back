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
            .prefetch_related("restrictions")
            .order_by("user__first_name", "user__last_name")
        )
        return Response([
            {
                "id": membership.user_id,
                "email": membership.user.email,
                "full_name": membership.user.get_full_name(),
                "initials": membership.user.initials,
                "role": membership.role.code,
                "role_name": membership.role.name,
                "is_external": membership.user.is_external,
                "is_active": membership.user.is_active,
                "language": membership.user.language or "",
                "area_restrictions": [
                    ref for restriction in membership.restrictions.all()
                    for ref in restriction.refs
                ],
            }
            for membership in memberships
        ])


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
        if role_code not in {role.value for role in Role}:
            return Response({"type": "unknown_role", "title": "Rol desconocido", "status": 400},
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

        is_external = role_code == Role.EXTERNAL_INSPECTOR.value
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

        Membership.objects.create(user=user, company_id=request.company_id, role=role,
                                  is_default=True)
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

        role_code = request.data.get("role")
        if role_code:
            if role_code not in {role.value for role in Role}:
                return Response({"type": "unknown_role", "status": 400}, status=400)
            # Locking yourself out of your own company is the classic footgun.
            if membership.user_id == request.user.id and role_code != membership.role.code:
                raise PermissionDenied("No puedes cambiar tu propio rol")
            role = RoleModel.objects.filter(company_id=request.company_id, code=role_code).first()
            if role is None:
                return Response({"type": "unknown_role", "status": 400}, status=400)
            membership.role = role
            membership.save(update_fields=["role"])

        if "is_active" in request.data:
            if membership.user_id == request.user.id:
                raise PermissionDenied("No puedes desactivarte a ti mismo")
            membership.user.is_active = bool(request.data["is_active"])
            membership.user.save(update_fields=["is_active"])

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

        return Response({
            "id": membership.user_id,
            "full_name": membership.user.get_full_name(),
            "initials": membership.user.initials,
            "role": membership.role.code,
            "role_name": membership.role.name,
            "is_active": membership.user.is_active,
            "area_restrictions": [
                ref for restriction in membership.restrictions.all() for ref in restriction.refs
            ],
        })

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
