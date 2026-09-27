from __future__ import annotations

from functools import lru_cache


def resolve_company(user, header_value: str | None) -> int | None:
    """The active tenant for this request. A company id in a payload is never
    trusted; only the header, and only if the user belongs to it."""
    from modules.security.infrastructure.models import Membership

    memberships = Membership.objects.filter(user=user).select_related("company")
    if header_value:
        wanted = int(header_value)
        if not memberships.filter(company_id=wanted).exists():
            raise PermissionError(wanted)
        return wanted
    default = memberships.filter(is_default=True).first() or memberships.first()
    return default.company_id if default else None


def permissions_for(user, company_id: int | None) -> frozenset[str]:
    if user.is_superuser:
        return _all_permission_codes()
    if company_id is None:
        return frozenset()
    from modules.security.infrastructure.models import Membership

    membership = (
        Membership.objects.filter(user=user, company_id=company_id)
        .prefetch_related("role__permissions")
        .first()
    )
    if membership is None:
        return frozenset()
    return frozenset(
        p.code for p in membership.role.permissions.all() if p.is_active
    )


def visible_companies(user) -> list[dict]:
    from modules.core.infrastructure.models import Company
    from modules.security.infrastructure.models import Membership

    if user.is_superuser:
        rows = Company.objects.filter(is_active=True)
        return [{"id": c.id, "name": c.name, "role": "platform_admin"} for c in rows]
    memberships = Membership.objects.filter(user=user).select_related("company", "role")
    return [
        {"id": m.company_id, "name": m.company.name, "role": m.role.code}
        for m in memberships
    ]


def allowed_area_ids(user, company_id: int) -> list[int] | None:
    """None means no restriction. An empty list means the user sees nothing,
    which is different and must not collapse to 'everything'."""
    from modules.security.infrastructure.models import Membership

    membership = Membership.objects.filter(user=user, company_id=company_id).first()
    if membership is None:
        return []
    restrictions = list(membership.restrictions.filter(scope="area"))
    if not restrictions:
        return None
    return [int(ref) for r in restrictions for ref in r.refs]


@lru_cache(maxsize=1)
def _all_permission_codes() -> frozenset[str]:
    from modules.security.infrastructure.models import Permission

    return frozenset(Permission.objects.filter(is_active=True).values_list("code", flat=True))


def build_actor(user, company_id: int):
    """The request's Actor, built once and handed to the policies.

    Policies never see a Django user: that is what keeps the authorization
    rules in `security/domain/policies.py` readable and unit-testable.
    """
    from modules.security.domain.actor import Actor, Role, behaviour_of
    from modules.security.infrastructure.models import Membership

    if user.is_superuser:
        return Actor(
            user_id=user.id, company_id=company_id, role=Role.PLATFORM_ADMIN,
            permissions=_all_permission_codes(), area_ids=None,
        )
    membership = (
        Membership.objects.filter(user=user, company_id=company_id)
        .select_related("role")
        .prefetch_related("role__permissions", "restrictions")
        .first()
    )
    if membership is None:
        return Actor(
            user_id=user.id, company_id=company_id, role=Role.CLIENT_VIEWER,
            permissions=frozenset(), area_ids=frozenset(),
        )
    areas = allowed_area_ids(user, company_id)
    return Actor(
        user_id=user.id,
        company_id=company_id,
        # `Role(code)` raised on every role a company made itself, so a user
        # given "Gerente General" could not load a single screen.
        role=behaviour_of(membership.role.base_role or membership.role.code),
        role_code=membership.role.code,
        permissions=frozenset(p.code for p in membership.role.permissions.all() if p.is_active),
        area_ids=None if areas is None else frozenset(areas),
    )
