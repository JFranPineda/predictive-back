"""Which installation a licence covers: two of three identifiers must match."""

from datetime import date

import pytest

from modules.licensing.domain.installation import (
    InstallationCodeError,
    InstallationFingerprint,
    belongs_to,
    installation_fingerprint,
)
from modules.licensing.domain.license import (
    License,
    LicenseStatus,
    TrustedKeys,
    evaluate,
    issue,
    verify,
)
from modules.licensing.domain.signing import generate_signing_key, public_key_text

HERE = installation_fingerprint("8d6f0c1e-ipsa", 7698282848465526823, "c0ffee00machine")
TODAY = date(2026, 10, 19)


def _licence(installation: InstallationFingerprint = HERE, **overrides) -> License:
    values = {
        "tenant_code": "ipsa", "plan": "gestionado", "issued_at": date(2026, 10, 1),
        "valid_until": date(2027, 1, 19), "license_id": "lic-ipsa", "grace_days": 30,
        "installation": installation, **overrides,
    }
    return License(**values)


def _elsewhere(**changes: str) -> InstallationFingerprint:
    values = {"installation_id": HERE.installation_id, "pg_system_id": HERE.pg_system_id,
              "machine_id": HERE.machine_id, **changes}
    return InstallationFingerprint(**values)


class TestFingerprint:
    def test_the_machine_id_never_travels_raw(self):
        # systemd: the machine id is confidential; hash it with an
        # application-specific key before it leaves the server.
        assert "c0ffee00machine" not in HERE.code()
        assert len(HERE.machine_id) == 32

    def test_it_is_stable(self):
        assert installation_fingerprint("8d6f0c1e-ipsa", "7698282848465526823", "c0ffee00machine") == HERE

    def test_the_code_round_trips(self):
        assert InstallationFingerprint.from_code(HERE.code()) == HERE

    @pytest.mark.parametrize("code", ["", "solo-uno", "a:b", "a:b:c:d"])
    def test_a_malformed_code_is_refused(self, code):
        with pytest.raises(InstallationCodeError):
            InstallationFingerprint.from_code(code)

    def test_a_missing_identifier_is_empty_not_an_error(self):
        partial = installation_fingerprint("8d6f0c1e-ipsa", None, "")
        assert partial.pg_system_id == "" and partial.machine_id == ""


class TestTwoOfThree:
    def test_all_three_match(self):
        assert belongs_to(HERE, HERE)

    @pytest.mark.parametrize("changed", ["installation_id", "pg_system_id", "machine_id"])
    def test_one_different_still_belongs(self, changed):
        assert belongs_to(HERE, _elsewhere(**{changed: "otro"}))

    def test_two_different_is_another_installation(self):
        assert not belongs_to(HERE, _elsewhere(pg_system_id="otro", machine_id="otra"))

    def test_a_missing_identifier_counts_as_different(self):
        # A cloned VM without /etc/machine-id: one miss, still two of three.
        assert belongs_to(HERE, _elsewhere(machine_id=""))
        assert not belongs_to(HERE, _elsewhere(pg_system_id="", machine_id=""))

    def test_two_empty_identifiers_do_not_match_each_other(self):
        licensed = _elsewhere(pg_system_id="", machine_id="")
        assert not belongs_to(licensed, _elsewhere(pg_system_id="", machine_id=""))

    def test_an_unbound_licence_belongs_anywhere(self):
        assert belongs_to(InstallationFingerprint(), _elsewhere(pg_system_id="x", machine_id="y"))


class TestVerdict:
    def test_its_own_installation_is_active(self):
        verdict = evaluate(_licence(), today=TODAY, installation=HERE)
        assert verdict.status is LicenseStatus.ACTIVE and not verdict.read_only

    def test_after_moving_the_application_it_stays_active(self):
        verdict = evaluate(_licence(), today=TODAY, installation=_elsewhere(machine_id="servidor-nuevo"))
        assert verdict.status is LicenseStatus.ACTIVE

    def test_another_installation_reads_but_does_not_write(self):
        verdict = evaluate(_licence(), today=TODAY, installation=_elsewhere(pg_system_id="x", machine_id="y"))
        assert verdict.status is LicenseStatus.OTHER_INSTALLATION
        assert verdict.read_only and not verdict.blocks
        assert "license fingerprint" in verdict.reason

    def test_an_expired_licence_elsewhere_is_still_expired(self):
        elsewhere = _elsewhere(pg_system_id="x", machine_id="y")
        verdict = evaluate(_licence(), today=date(2027, 6, 1), installation=elsewhere)
        assert verdict.status is LicenseStatus.EXPIRED and verdict.blocks

    def test_a_bound_licence_ignores_the_old_database_fingerprint(self):
        # Moving the database is normal IT work: two of three decide, not the
        # database name and host.
        licence = _licence(database_fingerprint="fp-viejo")
        verdict = evaluate(licence, today=TODAY, installation=HERE, database_fingerprint="fp-nuevo")
        assert verdict.status is LicenseStatus.ACTIVE

    def test_an_unbound_licence_keeps_the_database_check(self):
        licence = _licence(installation=InstallationFingerprint(), database_fingerprint="fp-viejo")
        verdict = evaluate(licence, today=TODAY, database_fingerprint="fp-nuevo")
        assert verdict.status is LicenseStatus.INVALID


class TestToken:
    def test_the_token_carries_the_installation(self):
        key = generate_signing_key()
        restored = verify(issue(_licence(), key), TrustedKeys(public_key=public_key_text(key)))
        assert restored.installation == HERE

    def test_a_token_without_one_is_unbound(self):
        key = generate_signing_key()
        unbound = _licence(installation=InstallationFingerprint())
        restored = verify(issue(unbound, key), TrustedKeys(public_key=public_key_text(key)))
        assert not restored.installation.is_bound
