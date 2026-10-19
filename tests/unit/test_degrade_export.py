"""When the subscription lapses: reading and exporting stay, working and
reports go (v4 Phase 4). And the system never deletes or encrypts what the
customer owns."""

import pathlib
import re
from datetime import date

import pytest

from modules.licensing.domain.export import (
    EXCEL_MAX_ROWS,
    EXCLUDED_TABLES,
    redact,
    sheet_name,
    split_rows,
)
from modules.licensing.domain.license import Access, License, LicenseStatus, LicenseVerdict, evaluate
from modules.licensing.infrastructure.middleware import classify

LICENCE = License(
    tenant_code="ipsa", plan="gestionado", issued_at=date(2026, 10, 1),
    valid_until=date(2027, 1, 19), license_id="lic-ipsa", grace_days=30,
)
ACTIVE = evaluate(LICENCE, today=date(2026, 12, 1))
GRACE = evaluate(LICENCE, today=date(2027, 2, 1))
EXPIRED = evaluate(LICENCE, today=date(2027, 3, 1))


class TestWhatEachStateAllows:
    def test_inside_the_term_everything(self):
        assert all(ACTIVE.allows(access) for access in Access)

    def test_in_grace_everything_but_writing(self):
        assert GRACE.allows(Access.READ) and GRACE.allows(Access.EXPORT) and GRACE.allows(Access.REPORT)
        assert not GRACE.allows(Access.WRITE)

    def test_after_the_grace_reading_and_exporting_only(self):
        assert EXPIRED.status is LicenseStatus.EXPIRED and EXPIRED.lapsed
        assert EXPIRED.allows(Access.READ) and EXPIRED.allows(Access.EXPORT)
        assert not EXPIRED.allows(Access.WRITE) and not EXPIRED.allows(Access.REPORT)

    @pytest.mark.parametrize(
        "status", [LicenseStatus.REVOKED, LicenseStatus.SUSPENDED, LicenseStatus.INVALID]
    )
    def test_revoked_suspended_and_invalid_behave_like_expired(self, status):
        verdict = LicenseVerdict(status, True, 0, "motivo")
        assert verdict.lapsed
        assert verdict.allows(Access.READ) and verdict.allows(Access.EXPORT)
        assert not verdict.allows(Access.WRITE) and not verdict.allows(Access.REPORT)

    @pytest.mark.parametrize("status", [LicenseStatus.OTHER_INSTALLATION, LicenseStatus.CLOCK_BEHIND])
    def test_installation_and_clock_only_take_writing(self, status):
        verdict = LicenseVerdict(status, True, 10, "motivo")
        assert not verdict.lapsed and verdict.allows(Access.REPORT) and not verdict.allows(Access.WRITE)

    def test_no_state_ever_takes_reading_or_exporting(self):
        # The exit guarantee: whatever happens to the licence, the customer
        # sees and takes their data.
        for status in LicenseStatus:
            verdict = LicenseVerdict(status, True, 0, "motivo")
            assert verdict.allows(Access.READ) and verdict.allows(Access.EXPORT)

    def test_after_the_grace_the_reason_says_what_still_works(self):
        assert "2027-01-19" in EXPIRED.reason
        assert "consultar y exportar" in EXPIRED.reason


class TestClassifyingRoutes:
    @pytest.mark.parametrize(("method", "path", "access"), [
        ("GET", "/api/v1/readings/", Access.READ),
        ("HEAD", "/api/v1/equipment/12/", Access.READ),
        ("OPTIONS", "/api/v1/readings/", Access.READ),
        ("POST", "/api/v1/readings/", Access.WRITE),
        ("PATCH", "/api/v1/equipment/12/", Access.WRITE),
        ("DELETE", "/api/v1/media/7/", Access.WRITE),
        ("GET", "/api/v1/reports/mpd/", Access.REPORT),
        ("GET", "/api/v1/reports/end/", Access.REPORT),
        ("GET", "/api/v1/reports/monthly/", Access.REPORT),
        ("GET", "/api/v1/reports/corrective/", Access.REPORT),
        ("GET", "/api/v1/ut-rollers/orders/4/groups/9/report/", Access.REPORT),
        ("GET", "/api/v1/activity/export/", Access.EXPORT),
        ("GET", "/api/v1/asset-groups/3/matrix/export/", Access.EXPORT),
        ("GET", "/api/v1/history/", Access.EXPORT),
        ("GET", "/api/v1/history/activity/2026-09/", Access.EXPORT),
    ])
    def test_each_route_has_its_kind(self, method, path, access):
        assert classify(method, path) is access

    def test_the_list_of_orders_to_report_on_is_data_not_a_report(self):
        assert classify("GET", "/api/v1/reports/orders/") is Access.READ

    def test_writing_through_an_export_or_report_path_is_still_writing(self):
        # Archiving history or editing a UT report changes data.
        assert classify("POST", "/api/v1/history/") is Access.WRITE
        assert classify("PATCH", "/api/v1/ut-rollers/orders/4/groups/9/report/") is Access.WRITE


class TestExportPieces:
    def test_sheet_names_fit_excel(self):
        used: set[str] = set()
        name = sheet_name("thresholds_thresholdsetversioncriterion", 1, used)
        assert len(name) <= 31 and name in used

    def test_a_split_table_says_which_part(self):
        used: set[str] = set()
        assert sheet_name("measurements_reading", 1, used) == "measurements_reading"
        assert sheet_name("measurements_reading", 2, used) == "measurements_reading (2)"

    def test_two_long_tables_never_share_a_sheet(self):
        used: set[str] = set()
        first = sheet_name("x" * 40 + "_alpha", 1, used)
        second = sheet_name("x" * 40 + "_beta", 1, used)
        assert first != second and len(second) <= 31

    def test_rows_split_at_the_excel_limit(self):
        parts = list(split_rows(iter(range(EXCEL_MAX_ROWS + 3)), EXCEL_MAX_ROWS))
        assert [len(part) for part in parts] == [EXCEL_MAX_ROWS, 3]

    def test_an_empty_table_still_gets_its_sheet(self):
        assert list(split_rows(iter([]), EXCEL_MAX_ROWS)) == [[]]

    def test_passwords_and_sessions_never_leave(self):
        assert redact("security_user", ["id", "email", "password"], (1, "a@b.pe", "pbkdf2$...")) == (
            1, "a@b.pe", "!exportado-sin-contraseña",
        )
        assert "django_session" in EXCLUDED_TABLES

    def test_anything_else_travels_untouched(self):
        assert redact("measurements_reading", ["id", "value"], (1, 2.5)) == (1, 2.5)


def test_licensing_never_deletes_or_encrypts_customer_data():
    """Ley 30096 and our exit guarantee: no licence state, and no code in the
    licensing module, removes or scrambles what the customer owns. The only
    file it may remove is a previous export archive, a copy we made."""
    root = pathlib.Path(__file__).resolve().parents[2] / "modules" / "licensing"
    # Scrambling data takes a symmetric cipher; encrypting our own signing
    # key (a PEM serialization) does not use one.
    forbidden = re.compile(
        r"\.delete\(|DELETE\s+FROM|TRUNCATE|DROP\s+TABLE|shutil\.rmtree|\bFernet\b|AESGCM|ChaCha20|Cipher\("
    )
    offenders = [
        f"{path.relative_to(root)}:{number}"
        for path in root.rglob("*.py") if "migrations" not in path.parts
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if forbidden.search(line) and "previous export" not in line
    ]
    assert offenders == []
