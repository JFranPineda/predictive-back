"""The key that ties a customer's on-premise database to our hosted system."""

from datetime import date

import pytest

from modules.licensing.domain.license import (
    BadSignature,
    License,
    LicenseLimits,
    LicenseStatus,
    MalformedToken,
    check_limit,
    database_fingerprint,
    evaluate,
    issue,
    verify,
)

SECRET = "server-side-secret-never-shipped-to-a-customer"

AMBEV = License(
    tenant_code="ambev",
    plan="enterprise",
    issued_at=date(2026, 1, 1),
    valid_until=date(2026, 12, 31),
    license_id="lic-0001",
    grace_days=15,
    limits=LicenseLimits(max_plants=2, max_equipment=600, max_users=25, max_external_users=10),
    modules=("core", "assets", "measurements", "vibration", "thermography"),
    database_fingerprint="fp-ambev",
)


class TestToken:
    def test_a_token_round_trips(self):
        restored = verify(issue(AMBEV, SECRET), SECRET)
        assert restored == AMBEV

    def test_a_tampered_payload_is_rejected(self):
        token = issue(AMBEV, SECRET)
        body, _, signature = token.partition(".")
        forged = f"{body[:-4]}AAAA.{signature}"
        with pytest.raises((BadSignature, MalformedToken)):
            verify(forged, SECRET)

    def test_another_secret_cannot_mint_a_licence(self):
        with pytest.raises(BadSignature):
            verify(issue(AMBEV, "stolen-guess"), SECRET)

    def test_the_signature_is_checked_before_the_payload_is_read(self):
        # Parsing first would let a forged token pick its own plan.
        with pytest.raises(BadSignature):
            verify("eyJwbGFuIjoiZW50ZXJwcmlzZSJ9.not-a-signature", SECRET)

    @pytest.mark.parametrize("token", ["", "no-dot", ".", "abc."])
    def test_garbage_is_refused_without_crashing(self, token):
        with pytest.raises((MalformedToken, BadSignature)):
            verify(token, SECRET)


class TestLifecycle:
    def test_inside_the_term_it_just_works(self):
        verdict = evaluate(AMBEV, today=date(2026, 6, 1), database_fingerprint="fp-ambev")
        assert verdict.status is LicenseStatus.ACTIVE
        assert not verdict.read_only and not verdict.blocks

    def test_warns_a_month_out(self):
        assert evaluate(AMBEV, today=date(2026, 12, 10)).should_warn

    def test_expiry_degrades_to_read_only_before_it_blocks(self):
        # Cutting a crew off mid-round over a three-day-late invoice makes an
        # enemy, not a payment.
        verdict = evaluate(AMBEV, today=date(2027, 1, 5))
        assert verdict.status is LicenseStatus.GRACE
        assert verdict.read_only and not verdict.blocks

    def test_after_the_grace_period_it_blocks(self):
        verdict = evaluate(AMBEV, today=date(2027, 1, 20))
        assert verdict.status is LicenseStatus.EXPIRED and verdict.blocks

    def test_revocation_is_immediate(self):
        verdict = evaluate(AMBEV, today=date(2026, 6, 1), revoked=frozenset({"lic-0001"}))
        assert verdict.status is LicenseStatus.REVOKED and verdict.blocks

    def test_suspension_blocks_without_touching_the_token(self):
        verdict = evaluate(AMBEV, today=date(2026, 6, 1), suspended=True)
        assert verdict.status is LicenseStatus.SUSPENDED

    def test_the_last_day_of_the_term_is_still_active(self):
        assert evaluate(AMBEV, today=date(2026, 12, 31)).status is LicenseStatus.ACTIVE


class TestDatabaseBinding:
    def test_a_licence_issued_for_one_database_does_not_travel(self):
        verdict = evaluate(AMBEV, today=date(2026, 6, 1), database_fingerprint="fp-otro-cliente")
        assert verdict.status is LicenseStatus.INVALID
        assert "base de datos" in verdict.reason

    def test_a_licence_with_no_fingerprint_is_not_bound(self):
        unbound = License(**{**AMBEV.__dict__, "database_fingerprint": ""}) if hasattr(AMBEV, "__dict__") else None
        del unbound
        loose = License(
            tenant_code="ambev", plan="basic", issued_at=date(2026, 1, 1),
            valid_until=date(2026, 12, 31), license_id="lic-0002",
        )
        assert evaluate(loose, today=date(2026, 6, 1), database_fingerprint="cualquiera").status is (
            LicenseStatus.ACTIVE
        )

    def test_the_fingerprint_is_stable_and_case_insensitive(self):
        first = database_fingerprint(tenant_code="ambev", database_name="predictive", host="DB.Cliente.com")
        second = database_fingerprint(tenant_code="AMBEV", database_name="Predictive", host="db.cliente.com")
        assert first == second

    def test_different_databases_fingerprint_differently(self):
        assert database_fingerprint(tenant_code="a", database_name="x", host="h") != (
            database_fingerprint(tenant_code="a", database_name="y", host="h")
        )


class TestEntitlements:
    def test_modules_outside_the_plan_are_not_installable(self):
        assert AMBEV.allows_module("vibration")
        assert not AMBEV.allows_module("ultrasound")

    def test_an_empty_module_list_means_everything(self):
        everything = License(
            tenant_code="x", plan="enterprise", issued_at=date(2026, 1, 1),
            valid_until=date(2026, 12, 31), license_id="lic-3",
        )
        assert everything.allows_module("whatever")

    def test_limits_stop_one_before_the_ceiling(self):
        assert check_limit(AMBEV, "equipment", 599)
        assert not check_limit(AMBEV, "equipment", 600)

    def test_the_real_plant_fits_the_contracted_plan(self):
        # 558 equipments in the source RGP against a 600 ceiling.
        assert check_limit(AMBEV, "equipment", 558)

    def test_an_unset_limit_is_no_limit(self):
        loose = License(
            tenant_code="x", plan="enterprise", issued_at=date(2026, 1, 1),
            valid_until=date(2026, 12, 31), license_id="lic-4",
        )
        assert check_limit(loose, "equipment", 10_000)
