"""The date the licence is judged by: the server clock, checked against the
highest date the installation has seen under the licence in force."""

from datetime import UTC, date, datetime, timedelta

from modules.licensing.domain.clock import (
    ClockReference,
    advanced,
    clock_floor,
    read_reference,
    sign_reference,
)
from modules.licensing.domain.license import License, LicenseStatus, evaluate

INSTALLATION = "8d6f0c1e-ipsa"
SEEN = datetime(2026, 10, 19, 15, 0, tzinfo=UTC)
LICENCE = License(
    tenant_code="ipsa", plan="gestionado", issued_at=date(2026, 10, 1),
    valid_until=date(2027, 1, 19), license_id="lic-ipsa", grace_days=30,
)
REFERENCE = ClockReference(license_id="lic-ipsa", seen_at=SEEN, reading_baseline=10536)


def _verdict(now: datetime, floor: datetime):
    return evaluate(LICENCE, now=now, clock_floor=floor)


class TestBehind:
    def test_48_hours_behind_reads_but_does_not_write(self):
        verdict = _verdict(SEEN - timedelta(hours=48), SEEN)
        assert verdict.status is LicenseStatus.CLOCK_BEHIND
        assert verdict.read_only and not verdict.lapsed
        # The dates are what the customer's IT needs to fix the clock.
        assert "2026-10-17" in verdict.reason and "2026-10-19" in verdict.reason

    def test_once_the_clock_is_right_it_is_active_again(self):
        assert _verdict(SEEN + timedelta(minutes=5), SEEN).status is LicenseStatus.ACTIVE

    def test_less_than_24_hours_changes_nothing(self):
        # Peru is UTC-5: a wrong time zone alone must never trip it.
        assert _verdict(SEEN - timedelta(hours=23), SEEN).status is LicenseStatus.ACTIVE

    def test_no_floor_means_the_current_time_is_trusted(self):
        assert evaluate(LICENCE, now=SEEN - timedelta(days=400)).status is not LicenseStatus.CLOCK_BEHIND

    def test_a_behind_clock_does_not_move_the_expiry(self):
        # Judging expiry by the remembered date would turn a clock that once
        # jumped forward into a blocked plant. Read-only is enough.
        verdict = _verdict(SEEN, SEEN + timedelta(days=200))
        assert verdict.status is LicenseStatus.CLOCK_BEHIND and not verdict.lapsed


class TestFloor:
    def test_the_licence_date_is_the_floor_we_signed(self):
        floor = clock_floor(LICENCE, reference=None, latest_reading_at=None)
        assert floor == datetime(2026, 10, 1, tzinfo=UTC)

    def test_it_is_the_highest_date_seen(self):
        later = SEEN + timedelta(days=3)
        assert clock_floor(LICENCE, reference=REFERENCE, latest_reading_at=later) == later
        assert clock_floor(LICENCE, reference=REFERENCE, latest_reading_at=None) == SEEN

    def test_each_licence_starts_the_reference_again(self):
        # A clock once set to 2027 by mistake: a new licence is the way out.
        poisoned = ClockReference(license_id="lic-anterior", seen_at=datetime(2027, 10, 19, tzinfo=UTC))
        assert clock_floor(LICENCE, reference=poisoned, latest_reading_at=None) == datetime(
            2026, 10, 1, tzinfo=UTC
        )


class TestAdvancing:
    def test_a_new_licence_gets_a_fresh_reference(self):
        fresh = advanced(None, license_id="lic-ipsa", now=SEEN, reading_baseline=10536)
        assert fresh == REFERENCE

    def test_it_moves_forward_at_most_once_an_hour(self):
        soon = SEEN + timedelta(minutes=30)
        assert advanced(REFERENCE, license_id="lic-ipsa", now=soon, reading_baseline=0) is None
        later = advanced(REFERENCE, license_id="lic-ipsa", now=SEEN + timedelta(hours=2), reading_baseline=0)
        assert later.seen_at == SEEN + timedelta(hours=2)
        assert later.reading_baseline == 10536

    def test_it_never_moves_back(self):
        earlier = SEEN - timedelta(days=2)
        assert advanced(REFERENCE, license_id="lic-ipsa", now=earlier, reading_baseline=0) is None

    def test_another_licence_replaces_it(self):
        replaced = advanced(REFERENCE, license_id="lic-nueva", now=SEEN, reading_baseline=11000)
        assert replaced == ClockReference(license_id="lic-nueva", seen_at=SEEN, reading_baseline=11000)


class TestStoredReference:
    def test_it_round_trips_signed(self):
        stored = sign_reference(REFERENCE, tenant="ipsa", installation_id=INSTALLATION)
        assert read_reference(stored, tenant="ipsa", installation_id=INSTALLATION) == REFERENCE

    def test_an_edited_value_is_unreadable_not_trusted(self):
        # A flipped byte that turns 2026 into 2096 must not leave the plant in
        # read-only for seventy years.
        stored = sign_reference(REFERENCE, tenant="ipsa", installation_id=INSTALLATION)
        stored["seen_at"] = stored["seen_at"].replace("2026", "2096")
        assert read_reference(stored, tenant="ipsa", installation_id=INSTALLATION) is None

    def test_another_installation_or_tenant_cannot_read_it(self):
        stored = sign_reference(REFERENCE, tenant="ipsa", installation_id=INSTALLATION)
        assert read_reference(stored, tenant="ipsa", installation_id="otra") is None
        assert read_reference(stored, tenant="ambev", installation_id=INSTALLATION) is None

    def test_a_time_without_zone_is_unreadable(self):
        # Compared with the aware clock it would raise in the middle of a request.
        naive = ClockReference(license_id="lic-ipsa", seen_at=SEEN.replace(tzinfo=None))
        stored = sign_reference(naive, tenant="ipsa", installation_id=INSTALLATION)
        assert read_reference(stored, tenant="ipsa", installation_id=INSTALLATION) is None

    def test_garbage_is_unreadable_never_an_error(self):
        for garbage in (None, {}, "texto", {"seen_at": "ayer"}, [], {"license": 1, "sig": 2}):
            assert read_reference(garbage, tenant="ipsa", installation_id=INSTALLATION) is None
