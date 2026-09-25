"""V3-02: who may take a photo back."""

from modules.security.domain.actor import Actor, Role
from modules.security.domain.policies import MediaRef, VisitRef, can_delete_media, can_edit_media

UPLOADER = 7
FIELD = frozenset({"services.view", "measurements.add_reading", "media.view", "media.upload"})


def technician(user_id=UPLOADER, extra=frozenset()):
    return Actor(user_id=user_id, company_id=1, role=Role.TECHNICIAN, permissions=FIELD | extra)


def engineer(user_id=UPLOADER):
    return Actor(user_id=user_id, company_id=1, role=Role.ENGINEER,
                 permissions=FIELD | {"services.close_visit"})


def visit(*, closed=False, participants=frozenset({UPLOADER})):
    return VisitRef(id=1, area_id=10, participant_ids=participants, lead_analyst_id=UPLOADER,
                    is_closed=closed, report_issued=False)


def test_uploader_removes_own_photo_from_an_open_visit():
    assert can_delete_media(technician(), MediaRef(uploaded_by_id=UPLOADER, visit=visit()))


def test_nobody_else_removes_it_without_the_permission():
    assert not can_delete_media(engineer(user_id=99), MediaRef(uploaded_by_id=UPLOADER, visit=visit()))


def test_a_closed_visit_is_a_record_even_for_its_uploader():
    assert not can_delete_media(technician(), MediaRef(uploaded_by_id=UPLOADER, visit=visit(closed=True)))
    assert not can_delete_media(engineer(), MediaRef(uploaded_by_id=UPLOADER, visit=visit(closed=True)))


def test_media_delete_removes_anything():
    admin = technician(user_id=1, extra=frozenset({"media.delete"}))
    assert can_delete_media(admin, MediaRef(uploaded_by_id=UPLOADER, visit=visit(closed=True)))
    assert can_delete_media(admin, MediaRef(uploaded_by_id=None))


def test_an_orphan_upload_is_never_anyones_but_the_admins():
    assert not can_delete_media(technician(), MediaRef(uploaded_by_id=None))


def test_a_file_outside_any_visit_follows_its_uploader():
    assert can_delete_media(technician(), MediaRef(uploaded_by_id=UPLOADER))
    assert not can_delete_media(technician(user_id=99), MediaRef(uploaded_by_id=UPLOADER))


def test_a_read_only_profile_never_edits_a_caption():
    viewer = Actor(user_id=5, company_id=1, role=Role.CLIENT_VIEWER, permissions=frozenset({"media.view"}))
    assert not can_edit_media(viewer, MediaRef(uploaded_by_id=UPLOADER, visit=visit()))


def test_the_crew_of_an_open_visit_edits_its_captions():
    assert can_edit_media(technician(), MediaRef(uploaded_by_id=99, visit=visit()))
    assert not can_edit_media(technician(), MediaRef(uploaded_by_id=99, visit=visit(closed=True)))
