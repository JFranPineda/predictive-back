"""Who is asking, reduced to what authorization needs.

Built once per request from the membership, and passed down. Policies never
receive a Django user or a request — that is what keeps them testable and what
keeps the rules in one readable place instead of scattered across views.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    PLATFORM_ADMIN = "platform_admin"
    COMPANY_ADMIN = "company_admin"
    ENGINEER = "engineer"
    PLANNER = "planner"
    TECHNICIAN = "technician"
    # Outside contractor: reads the asset, writes only his own service.
    EXTERNAL_INSPECTOR = "external_inspector"
    CLIENT_VIEWER = "client_viewer"


@dataclass(frozen=True, slots=True)
class Actor:
    user_id: int
    company_id: int
    role: Role
    permissions: frozenset[str]
    # None means "no area restriction". An empty frozenset means "no areas at
    # all", which is a different thing and must not collapse into "everything".
    area_ids: frozenset[int] | None = None

    def has(self, permission: str) -> bool:
        return permission in self.permissions

    def may_reach_area(self, area_id: int | None) -> bool:
        if self.area_ids is None:
            return True
        return area_id is not None and area_id in self.area_ids
