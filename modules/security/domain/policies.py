"""Authorization rules, as plain predicates.

The external inspector is the case that shapes this module: he must read the
equipment — drawings, nameplate, history — and write only the service he
himself performed, only while it is still open.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .actor import Actor, Role


@dataclass(frozen=True, slots=True)
class VisitRef:
    """The bits of a service visit a policy needs, with no ORM attached."""

    id: int
    area_id: int
    participant_ids: frozenset[int]
    lead_analyst_id: int | None
    is_closed: bool
    report_issued: bool
    visited_on: date | None = None


READ_ONLY_ROLES = frozenset({Role.CLIENT_VIEWER, Role.EXTERNAL_INSPECTOR})


def can_view_equipment(actor: Actor, area_id: int) -> bool:
    return actor.has("assets.view_equipment") and actor.may_reach_area(area_id)


def can_edit_equipment(actor: Actor, area_id: int) -> bool:
    """Reading the asset never implies changing it. An inspector who could
    retag equipment would silently rewrite somebody else's plant."""
    if actor.role in READ_ONLY_ROLES:
        return False
    return actor.has("assets.manage_equipment") and actor.may_reach_area(area_id)


def can_view_visit(actor: Actor, visit: VisitRef) -> bool:
    if not actor.may_reach_area(visit.area_id):
        return False
    if actor.role is Role.EXTERNAL_INSPECTOR:
        # He sees the plant's history like anyone else; ownership only gates
        # writing. Hiding other people's findings from an analyst would make
        # trending useless.
        return actor.has("services.view")
    return actor.has("services.view")


def can_edit_visit(actor: Actor, visit: VisitRef) -> bool:
    """The rule the brief asks for: own service, still open."""
    if visit.report_issued:
        return False
    if not actor.may_reach_area(visit.area_id):
        return False
    if actor.role in {Role.PLATFORM_ADMIN, Role.COMPANY_ADMIN, Role.ENGINEER}:
        return actor.has("services.close_visit")
    if actor.role in {Role.TECHNICIAN, Role.EXTERNAL_INSPECTOR}:
        return (
            actor.has("measurements.add_reading")
            and actor.user_id in visit.participant_ids
            and not visit.is_closed
        )
    return False


def can_record_reading(actor: Actor, visit: VisitRef) -> bool:
    return can_edit_visit(actor, visit) and actor.has("measurements.add_reading")


def can_upload_media(actor: Actor, visit: VisitRef) -> bool:
    return can_edit_visit(actor, visit) and actor.has("media.upload")


@dataclass(frozen=True, slots=True)
class MediaRef:
    """Who uploaded a file and, if it is evidence of a visit, that visit."""

    uploaded_by_id: int | None
    visit: VisitRef | None = None


def can_edit_media(actor: Actor, media: MediaRef) -> bool:
    """The caption under a capture *is* the finding, so it follows the same
    rule as the visit's other field data; a read-only profile never edits it."""
    if not actor.has("media.upload"):
        return False
    return media.visit is None or can_upload_media(actor, media.visit)


def can_delete_media(actor: Actor, media: MediaRef) -> bool:
    """`media.delete` removes anything. Without it, only the uploader may take
    a file back — and evidence of a visit only while that visit is still open:
    a closed visit is a record, not a draft."""
    if actor.has("media.delete"):
        return True
    if media.uploaded_by_id is None or media.uploaded_by_id != actor.user_id:
        return False
    if media.visit is None:
        return actor.has("media.upload")
    return not media.visit.is_closed and can_upload_media(actor, media.visit)


def can_write_log_entry(actor: Actor, visit: VisitRef) -> bool:
    """Notes, observations, conclusions and recommendations. An inspector may
    record what he saw; turning a finding into a closed recommendation is the
    engineer's call."""
    return can_edit_visit(actor, visit) and actor.has("diagnostics.add_entry")


def can_close_recommendation(actor: Actor) -> bool:
    return actor.role not in READ_ONLY_ROLES and actor.has("diagnostics.close_recommendation")


def can_issue_report(actor: Actor) -> bool:
    """Signing the document to the customer is never the contractor's."""
    return actor.role in {Role.PLATFORM_ADMIN, Role.COMPANY_ADMIN, Role.ENGINEER} and actor.has(
        "reports.issue"
    )


def can_change_order_status(actor: Actor) -> bool:
    """Only the administrator moves an order between planned, in progress,
    done and cancelled (V3-27); planning an order is not closing it."""
    return actor.role not in READ_ONLY_ROLES and actor.has("services.change_order_status")


def can_manage_thresholds(actor: Actor) -> bool:
    return actor.role not in READ_ONLY_ROLES and actor.has("thresholds.manage_set")


def visible_area_filter(actor: Actor) -> frozenset[int] | None:
    """What every queryset narrows by. None means no narrowing."""
    return actor.area_ids
