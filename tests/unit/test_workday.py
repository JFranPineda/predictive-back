"""Fase 3: the day a chief engineer closes, the ATS before the photo, and the
observation that starts with its picture."""

from datetime import UTC, datetime

import pytest

from modules.core.domain.manifest import Manifest
from modules.core.infrastructure.discovery import discover_manifests
from modules.workday.domain.rules import (
    UNLOCKED_MODULES,
    ObservationIncompleteError,
    PermitRef,
    Work,
    check_observation,
    day_closed,
    day_works,
    permit_valid,
)


def test_a_date_nobody_opened_is_not_closed():
    assert day_closed([]) is False


def test_the_day_locks_only_once_every_workday_of_it_is_closed():
    assert day_closed([True]) is False
    assert day_closed([False]) is True
    # Two plants: one still working keeps the date open.
    assert day_closed([False, True]) is False


def test_an_ats_counts_only_with_its_signed_copy():
    permits = [PermitRef(asset_group_id=7, has_document=False)]
    assert permit_valid(permits, 7, workday_open=True) is False
    permits.append(PermitRef(asset_group_id=7, has_document=True))
    assert permit_valid(permits, 7, workday_open=True) is True


def test_an_ats_is_for_its_own_train_and_its_own_open_day():
    permits = [PermitRef(asset_group_id=7, has_document=True)]
    assert permit_valid(permits, 8, workday_open=True) is False
    assert permit_valid(permits, 7, workday_open=False) is False


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
