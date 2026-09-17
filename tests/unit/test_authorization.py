"""T1: what an external inspector can and cannot do."""

from datetime import date

import pytest

from modules.security.domain.actor import Actor, Role
from modules.security.domain.policies import (
    VisitRef,
    can_close_recommendation,
    can_edit_equipment,
    can_edit_visit,
    can_issue_report,
    can_record_reading,
    can_upload_media,
    can_view_equipment,
    can_view_visit,
    can_write_log_entry,
)

INSPECTOR_PERMISSIONS = frozenset({
    "assets.view_equipment", "blueprints.view", "nameplate.view",
    "services.view", "measurements.view_reading", "measurements.add_reading",
    "media.view", "media.upload", "diagnostics.view", "diagnostics.add_entry",
})

ENGINEER_PERMISSIONS = INSPECTOR_PERMISSIONS | frozenset({
    "assets.manage_equipment", "services.close_visit", "reports.issue",
    "diagnostics.close_recommendation", "thresholds.manage_set",
})


def inspector(user_id=7, areas=None):
    return Actor(user_id=user_id, company_id=1, role=Role.EXTERNAL_INSPECTOR,
                 permissions=INSPECTOR_PERMISSIONS, area_ids=areas)


def engineer(user_id=1):
    return Actor(user_id=user_id, company_id=1, role=Role.ENGINEER,
                 permissions=ENGINEER_PERMISSIONS)


def visit(participants=(7,), closed=False, issued=False, area_id=10):
    return VisitRef(
        id=99, area_id=area_id, participant_ids=frozenset(participants),
        lead_analyst_id=next(iter(participants), None), is_closed=closed,
        report_issued=issued, visited_on=date(2026, 9, 1),
    )


class TestExternalInspectorReads:
    def test_sees_the_equipment(self):
        assert can_view_equipment(inspector(), area_id=10)

    def test_cannot_change_the_equipment(self):
        assert not can_edit_equipment(inspector(), area_id=10)

    def test_sees_visits_he_did_not_perform(self):
        # Trending needs the whole history; ownership gates writing, not reading.
        assert can_view_visit(inspector(), visit(participants=(42,)))

    def test_area_restriction_hides_the_rest_of_the_plant(self):
        scoped = inspector(areas=frozenset({10}))
        assert can_view_equipment(scoped, area_id=10)
        assert not can_view_equipment(scoped, area_id=11)

    def test_an_empty_area_set_means_nothing_not_everything(self):
        assert not can_view_equipment(inspector(areas=frozenset()), area_id=10)


class TestExternalInspectorWrites:
    def test_edits_his_own_open_visit(self):
        assert can_edit_visit(inspector(), visit(participants=(7,)))

    def test_cannot_edit_a_visit_he_did_not_perform(self):
        assert not can_edit_visit(inspector(), visit(participants=(42,)))

    def test_cannot_edit_his_own_visit_once_closed(self):
        assert not can_edit_visit(inspector(), visit(participants=(7,), closed=True))

    def test_nobody_edits_a_visit_whose_report_was_issued(self):
        issued = visit(participants=(7,), issued=True)
        assert not can_edit_visit(inspector(), issued)
        assert not can_edit_visit(engineer(), issued)

    @pytest.mark.parametrize("action", [can_record_reading, can_upload_media, can_write_log_entry])
    def test_readings_photos_and_notes_follow_the_same_ownership(self, action):
        assert action(inspector(), visit(participants=(7,)))
        assert not action(inspector(), visit(participants=(42,)))

    def test_shares_a_visit_with_a_second_inspector(self):
        # "quién o quiénes": a visit can have several people, each able to write.
        shared = visit(participants=(7, 8))
        assert can_edit_visit(inspector(user_id=7), shared)
        assert can_edit_visit(inspector(user_id=8), shared)


class TestWhatStaysWithTheOffice:
    def test_inspector_does_not_issue_reports(self):
        assert not can_issue_report(inspector())
        assert can_issue_report(engineer())

    def test_inspector_does_not_close_recommendations(self):
        assert not can_close_recommendation(inspector())
        assert can_close_recommendation(engineer())

    def test_engineer_edits_any_open_visit_in_his_scope(self):
        assert can_edit_visit(engineer(), visit(participants=(7,)))
        assert can_edit_visit(engineer(), visit(participants=(7,), closed=True))
