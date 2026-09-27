"""Q20: every write reads as one line of the activity log."""

from modules.activity.domain.describe import clean_client_events, describe_request
from modules.core.infrastructure.discovery import discover_manifests


def test_a_patch_names_the_record_and_the_fields_it_changed():
    event = describe_request(
        method="PATCH",
        path="/api/v1/service-orders/12/",
        status=200,
        fields=["standard", "notes"],
    )
    assert event.kind == "update"
    assert event.description == "Modificó orden de servicio #12 · campos: notes, standard"
    assert (event.object_type, event.object_id) == ("service-orders", "12")


def test_a_password_never_shows_among_the_changed_fields():
    event = describe_request(
        method="PATCH", path="/api/v1/users/4/", status=200, fields=["password", "email"]
    )
    assert "password" not in event.description
    assert "email" in event.description


def test_an_upload_names_its_files_and_where_they_went():
    event = describe_request(
        method="POST",
        path="/api/v1/service-visits/5/thermograms/",
        status=201,
        fields=["point"],
        files=["IR_0042.jpg"],
    )
    assert event.kind == "upload"
    assert event.description == "Subió «IR_0042.jpg» (termograma de visita de servicio #5)"


def test_a_verb_at_the_end_of_the_path_is_an_action():
    event = describe_request(method="POST", path="/api/v1/workdays/3/close/", status=200)
    assert event.kind == "action"
    assert event.description == "Cerró jornada #3"


def test_a_delete_is_a_baja():
    event = describe_request(method="DELETE", path="/api/v1/media/55/", status=204)
    assert (event.kind, event.description) == ("delete", "Eliminó archivo #55")


def test_a_refused_write_is_logged_as_refused():
    event = describe_request(method="POST", path="/api/v1/workdays/3/reopen/", status=403)
    assert event.kind == "denied"
    assert event.description == "No se pudo reabrir jornada #3 (sin permiso)"


def test_logins_tell_success_from_failure():
    ok = describe_request(method="POST", path="/api/v1/auth/login/", status=200, login_email="a@b.pe")
    bad = describe_request(method="POST", path="/api/v1/auth/login/", status=401, login_email="a@b.pe")
    assert ok.kind == "login"
    assert bad.kind == "login_failed"
    assert "a@b.pe" in bad.description


def test_reads_refreshes_and_the_logs_own_posts_are_not_events():
    assert describe_request(method="GET", path="/api/v1/service-orders/", status=200) is None
    assert describe_request(method="POST", path="/api/v1/auth/refresh/", status=200) is None
    assert describe_request(method="POST", path="/api/v1/activity/events/", status=204) is None
    assert describe_request(method="POST", path="/media/x.jpg", status=200) is None


def test_the_browser_may_only_report_clicks_page_changes_and_logouts():
    events = clean_client_events(
        [
            {"kind": "click", "label": "  Guardar \n cambios ", "path": "/alignment"},
            {"kind": "navigation", "path": "/workday", "label": "Jornada"},
            {"kind": "delete", "label": "falso"},
            {"kind": "click", "label": ""},
            "basura",
        ]
    )
    assert [e.kind for e in events] == ["click", "navigation"]
    assert events[0].description == "Clic en «Guardar cambios» (/alignment)"
    assert events[1].description == "Abrió /workday · Jornada"


def test_the_module_is_optional_and_observes_requests():
    manifest = next(m for m in discover_manifests() if m.code == "activity")
    assert manifest.is_core is False
    assert manifest.request_observer.endswith("observer.observe")


def test_a_module_is_named_by_its_code():
    event = describe_request(method="POST", path="/api/v1/modules/workday/install/", status=200)
    assert event.description == "Instaló módulo «workday»"


def test_the_refusal_says_why_in_words():
    closed = describe_request(method="POST", path="/api/v1/service-visits/9/entries/", status=423)
    assert closed.description == "No se pudo crear anotación de visita de servicio #9 (jornada cerrada)"


def test_a_generic_upload_says_what_the_file_belongs_to():
    event = describe_request(
        method="POST",
        path="/api/v1/media/",
        status=201,
        files=["crack.jpg"],
        owner=("equipment", "560"),
    )
    assert event.description == "Subió «crack.jpg» (equipo #560)"
