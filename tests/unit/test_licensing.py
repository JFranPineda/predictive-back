"""The licence: signed by us, verified wherever the program runs."""

import base64
import hashlib
import hmac
import json
from datetime import date

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from modules.licensing.domain.license import (
    BadSignature,
    License,
    LicenseError,
    LicenseLimits,
    LicenseStatus,
    MalformedToken,
    TrustedKeys,
    check_limit,
    database_fingerprint,
    evaluate,
    issue,
    token_version,
    verify,
)
from modules.licensing.domain.signing import (
    SigningKeyError,
    decrypt_signing_key,
    encrypt_signing_key,
    generate_signing_key,
    public_key_text,
)

SIGNING_KEY = generate_signing_key()
KEYS = TrustedKeys(public_key=public_key_text(SIGNING_KEY))
PASSWORD = "a-passphrase-long-enough"

# The v1 secret, and a token the HMAC code minted with it before v2 existed.
SECRET = "server-side-secret-never-shipped-to-a-customer"
V1_TOKEN = (
    "eyJmaW5nZXJwcmludCI6ImZwLWFtYmV2IiwiZ3JhY2UiOjE1LCJpZCI6ImxpYy0wMDAxIiwiaXNzdWVkIjoiMjAyNi0w"
    "MS0wMSIsImxpbWl0cyI6eyJtYXhfZXF1aXBtZW50Ijo2MDAsIm1heF9leHRlcm5hbF91c2VycyI6MTAsIm1heF9wbGFu"
    "dHMiOjIsIm1heF91c2VycyI6MjV9LCJtb2R1bGVzIjpbImNvcmUiLCJhc3NldHMiLCJtZWFzdXJlbWVudHMiLCJ2aWJy"
    "YXRpb24iLCJ0aGVybW9ncmFwaHkiXSwicGxhbiI6ImVudGVycHJpc2UiLCJ0ZW5hbnQiOiJhbWJldiIsInVudGlsIjoi"
    "MjAyNi0xMi0zMSIsInYiOjF9.uru_6lH0bpKPBapxt9GjM5wJ7plHbSsBYnpbF2FLjwQ"
)


def _encode(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _payload(token: str) -> dict:
    body = token.partition(".")[0]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


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
    def test_a_token_round_trips_with_only_the_public_key(self):
        assert verify(issue(AMBEV, SIGNING_KEY), KEYS) == AMBEV

    def test_a_new_token_is_version_2(self):
        assert token_version(issue(AMBEV, SIGNING_KEY)) == 2

    def test_a_tampered_payload_is_rejected(self):
        signature = issue(AMBEV, SIGNING_KEY).partition(".")[2]
        payload = _payload(issue(AMBEV, SIGNING_KEY))
        payload["limits"]["max_equipment"] = 6000
        with pytest.raises(BadSignature):
            verify(f"{_encode(payload)}.{signature}", KEYS)

    def test_a_tampered_signature_is_rejected(self):
        body, _, signature = issue(AMBEV, SIGNING_KEY).partition(".")
        flipped = ("A" if signature[0] != "A" else "B") + signature[1:]
        with pytest.raises(BadSignature):
            verify(f"{body}.{flipped}", KEYS)

    def test_another_key_cannot_mint_a_licence(self):
        with pytest.raises(BadSignature):
            verify(issue(AMBEV, generate_signing_key()), KEYS)

    def test_the_signature_is_checked_before_the_payload_is_read(self):
        # Parsing first would let a forged token pick its own plan.
        forged = _encode({"v": 2, "plan": "enterprise"})
        with pytest.raises(BadSignature):
            verify(f"{forged}.not-a-signature", KEYS)

    def test_no_installed_public_key_verifies_nothing(self):
        with pytest.raises(LicenseError):
            verify(issue(AMBEV, SIGNING_KEY), TrustedKeys(public_key=""))

    @pytest.mark.parametrize("token", ["", "no-dot", ".", "abc."])
    def test_garbage_is_refused_without_crashing(self, token):
        with pytest.raises((MalformedToken, BadSignature)):
            verify(token, KEYS)


class TestTransition:
    """v1 (HMAC) tokens keep working between reissuing and deploying, and only
    where the verifier holds the legacy secret."""

    def test_a_v1_token_still_verifies_with_the_legacy_secret(self):
        keys = TrustedKeys(public_key=KEYS.public_key, legacy_secret=SECRET)
        assert token_version(V1_TOKEN) == 1
        assert verify(V1_TOKEN, keys) == AMBEV

    def test_without_the_legacy_secret_no_v1_token_verifies(self):
        # An empty HMAC key is one anyone can compute: no secret, no v1.
        body = V1_TOKEN.partition(".")[0]
        anyones = base64.urlsafe_b64encode(hmac.new(b"", body.encode(), hashlib.sha256).digest())
        with pytest.raises(BadSignature):
            verify(f"{body}.{anyones.decode().rstrip('=')}", KEYS)
        with pytest.raises(BadSignature):
            verify(V1_TOKEN, KEYS)

    def test_a_v1_token_from_another_secret_is_refused(self):
        with pytest.raises(BadSignature):
            verify(V1_TOKEN, TrustedKeys(public_key=KEYS.public_key, legacy_secret="stolen-guess"))

    @pytest.mark.parametrize("version", [3, 0, None, "2", True])
    def test_an_unknown_version_is_malformed(self, version):
        # `True == 1` in Python: only the integers on the list are versions.
        payload = {**_payload(issue(AMBEV, SIGNING_KEY)), "v": version}
        keys = TrustedKeys(public_key=KEYS.public_key, legacy_secret=SECRET)
        with pytest.raises(MalformedToken):
            verify(f"{_encode(payload)}.c2lnbmF0dXJl", keys)


class TestSigningKeyFile:
    def test_the_file_is_encrypted(self):
        pem = encrypt_signing_key(SIGNING_KEY, PASSWORD)
        assert pem.startswith(b"-----BEGIN ENCRYPTED PRIVATE KEY-----")
        with pytest.raises(TypeError):
            serialization.load_pem_private_key(pem, password=None)

    def test_the_right_password_opens_it(self):
        restored = decrypt_signing_key(encrypt_signing_key(SIGNING_KEY, PASSWORD), PASSWORD)
        assert public_key_text(restored) == KEYS.public_key

    def test_a_wrong_password_says_so(self):
        pem = encrypt_signing_key(SIGNING_KEY, PASSWORD)
        with pytest.raises(SigningKeyError, match="contraseña"):
            decrypt_signing_key(pem, "not-the-passphrase-at-all")

    def test_an_unencrypted_key_is_refused(self):
        pem = SIGNING_KEY.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
        with pytest.raises(SigningKeyError, match="cifrad"):
            decrypt_signing_key(pem, PASSWORD)

    def test_a_short_password_is_refused(self):
        with pytest.raises(SigningKeyError, match="16"):
            encrypt_signing_key(SIGNING_KEY, "too-short")

    def test_a_key_of_another_kind_is_refused(self):
        # An SSH or TLS key picked by mistake: say so, do not crash at signing.
        other = ec.generate_private_key(ec.SECP256R1()).private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(PASSWORD.encode()),
        )
        with pytest.raises(SigningKeyError, match="Ed25519"):
            decrypt_signing_key(other, PASSWORD)


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
