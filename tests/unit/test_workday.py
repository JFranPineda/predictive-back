"""Fase 3: the day a chief engineer closes, the ATS before the photo, and the
observation that starts with its picture."""

from datetime import UTC, datetime

import pytest

from modules.core.domain.manifest import Manifest
from modules.core.infrastructure.discovery import discover_manifests
from modules.workday.domain.rules import (
    START_ROLES,
    UNLOCKED_MODULES,
    Ats,
    CrewMember,
    JobRef,
    ObservationIncompleteError,
    ServiceNotClosableError,
    Step,
    Work,
    ats_missing,
    check_closable,
    check_observation,
    day_closed,
    day_works,
    items_of,
    job_allows,
    job_started,
)


def test_a_date_nobody_opened_is_not_closed():
    assert day_closed([]) is False


def test_the_day_locks_only_once_every_workday_of_it_is_closed():
    assert day_closed([True]) is False
    assert day_closed([False]) is True
    # Two plants: one still working keeps the date open.
    assert day_closed([False, True]) is False


def test_a_service_starts_with_its_three_signatures_or_an_admin_unlock():
    assert START_ROLES == ("production_engineer", "service_leader", "plant_supervisor")
    assert job_started(["production_engineer", "service_leader"], unlocked=False) is False
    assert job_started([*START_ROLES, "crew"], unlocked=False) is True
    assert job_started([], unlocked=True) is True


def test_only_a_started_open_service_of_the_train_opens_its_fields():
    started = JobRef(asset_group_id=7, service_order_id=3, started=True, closed=False)
    assert job_allows([started], 7, 3) is True
    assert job_allows([started], 8, 3) is False
    # Another order's service does not open this one's fields.
    assert job_allows([started], 7, 4) is False
    # A write that names no order is covered by any started service.
    assert job_allows([started], 7, None) is True
    assert job_allows([JobRef(7, None, started=False, closed=False)], 7) is False
    assert job_allows([JobRef(7, None, started=True, closed=True)], 7) is False


def _ats(**changes):
    base = {
        "activity": "Alineamiento láser",
        "holder": "1A-MIG",
        "area": "Máquina de papel",
        "zone": "Prensa 1",
        "risk_category": "high",
        "ppe": "Casco, lentes",
        "tools": "Alineador SKF",
        "steps": (Step("Bloqueo", "Energía", "Atrapamiento", "A", 3, "LOTO"),),
        "crew": (CrewMember("Juan Ramos", True),),
    }
    base.update(changes)
    return Ats(**base)


def test_a_complete_signed_ats_misses_nothing():
    assert ats_missing(_ats()) == []


def test_the_ats_lists_what_it_still_lacks_in_form_order():
    missing = ats_missing(_ats(zone=" ", risk_category="", crew=(CrewMember("Abel López", False),)))
    assert missing == ["la zona", "la categoría del riesgo", "la firma de Abel López"]
    unevaluated = ats_missing(_ats(steps=(Step("Bloqueo", "Energía", "Atrapamiento", "", None, "LOTO"),)))
    assert unevaluated == ["la evaluación IPERC del paso 1"]


def test_the_final_hour_needs_a_started_service_and_a_complete_ats():
    with pytest.raises(ServiceNotClosableError, match="firmas de inicio"):
        check_closable(started=False, closed=False, missing=[])
    with pytest.raises(ServiceNotClosableError, match="el EPP"):
        check_closable(started=True, closed=False, missing=["el EPP"])
    check_closable(started=True, closed=False, missing=[])


def test_a_step_with_several_hazards_keeps_one_item_number():
    steps = [
        Step(text, "", "", "", None, "")
        for text in ("Verificar", "Mover tubería", "mover tubería ", "Empalme")
    ]
    assert items_of(steps) == [1, 2, 2, 3]


@pytest.mark.parametrize(
    ("has_photo", "visible", "text", "message"),
    [
        (False, True, "Se ajustaron pernos", "foto"),
        (True, None, "Se ajustaron pernos", "visible"),
        (True, False, "  ", "Describe"),
    ],
)
def test_an_observation_asks_for_the_photo_first(has_photo, visible, text, message):
    with pytest.raises(ObservationIncompleteError, match=message):
        check_observation(has_photo=has_photo, visible=visible, text=text)


def test_a_complete_observation_passes():
    check_observation(has_photo=True, visible=False, text="Se cambió la faja")


def test_the_days_works_run_in_the_order_they_started():
    def work(kind, id_, hour):
        started = datetime(2026, 9, 26, hour, tzinfo=UTC) if hour is not None else None
        return Work(kind, id_, "", "", "", "", (), started, None)

    ordered = day_works([work("visit", 1, 14), work("maintenance", 2, None), work("visit", 3, 8)])
    assert [w.id for w in ordered] == [3, 1, 2]


def test_people_and_platform_stay_writable_after_the_close():
    assert {"core", "security", "licensing", "workday"} <= UNLOCKED_MODULES
    assert "services" not in UNLOCKED_MODULES


def test_the_module_is_optional_and_declares_its_guard():
    manifest = next(m for m in discover_manifests() if m.code == "workday")
    assert manifest.is_core is False
    assert manifest.auto_install is False
    assert manifest.write_guard == "modules.workday.infrastructure.guard.guard"
    assert manifest.on_install == "modules.workday.infrastructure.setup.install"


def test_a_manifest_without_a_guard_vetoes_nothing():
    assert Manifest(code="x", name="x", version="1").write_guard is None
