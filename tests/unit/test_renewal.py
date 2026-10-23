"""Renewing a licence: the request that leaves the customer's network, the
rules a renewal file must pass, and what the online service may answer."""

from datetime import date

import pytest

from modules.licensing.application.renewal import renew_online
from modules.licensing.domain.installation import InstallationFingerprint, installation_fingerprint
from modules.licensing.domain.license import License, LicenseStatus, TrustedKeys, evaluate
from modules.licensing.domain.renewal import (
    RenewalRejectedError,
    RenewalRequest,
    check_renewal,
    renewal_answer,
)

HERE = installation_fingerprint("8d6f0c1e-ipsa", 7698282848465526823, "c0ffee00machine")
CURRENT = License(
    tenant_code="ipsa", plan="gestionado", issued_at=date(2026, 10, 1),
    valid_until=date(2027, 1, 19), license_id="lic-q1", grace_days=30, installation=HERE,
)
NEXT = License(
    tenant_code="ipsa", plan="gestionado", issued_at=date(2027, 1, 10),
    valid_until=date(2027, 4, 19), license_id="lic-q2", grace_days=30, installation=HERE,
)
REQUEST = RenewalRequest(
    tenant="ipsa", license_id="lic-q1", valid_until=date(2027, 1, 19),
    installation=HERE.code(), version="0.1.0", equipment=98, users=4,
)


class TestRequest:
    def test_it_says_exactly_what_leaves_the_network(self):
        # The customer's IT reads this before sending it. Nothing else goes:
        # no machine names, no readings, no people.
        assert REQUEST.text().splitlines() == [
            "PREDICTIVE · solicitud de licencia",
            "cliente: ipsa",
            "licencia: lic-q1",
            "vence: 2027-01-19",
            f"instalación: {HERE.code()}",
            "versión: 0.1.0",
            "equipos: 98",
            "usuarios: 4",
        ]

    def test_the_online_service_gets_the_same_fields(self):
        assert REQUEST.payload() == {
            "tenant": "ipsa", "license": "lic-q1", "until": "2027-01-19",
            "installation": HERE.code(), "version": "0.1.0", "equipment": 98, "users": 4,
        }

    def test_a_new_installation_asks_for_its_first_licence(self):
        # v4 Phase 6 (P6-c): the licence is issued for the installation, which
        # only exists once installed, so the first request has none to name.
        first = RenewalRequest(
            tenant="ipsa", license_id="", valid_until=None,
            installation=HERE.code(), version="0.1.0", equipment=0, users=1,
        )
        lines = first.text().splitlines()
        assert lines[2:4] == ["licencia: ninguna (primera licencia)", "vence: —"]
        assert [line.split(":")[0] for line in lines[1:]] == [
            "cliente", "licencia", "vence", "instalación", "versión", "equipos", "usuarios",
        ]
        assert first.payload()["license"] == "" and first.payload()["until"] is None


class TestRenewalFile:
    def test_the_next_period_for_this_installation_is_accepted(self):
        check_renewal(NEXT, tenant_code="ipsa", current=CURRENT, observed=HERE)

    def test_one_identifier_changed_still_two_of_three(self):
        moved = InstallationFingerprint(HERE.installation_id, HERE.pg_system_id, "otra-maquina")
        check_renewal(NEXT, tenant_code="ipsa", current=CURRENT, observed=moved)

    def test_another_installation_is_refused_and_says_why(self):
        elsewhere = InstallationFingerprint(HERE.installation_id, "otro-cluster", "otra-maquina")
        with pytest.raises(RenewalRejectedError, match="otra instalación"):
            check_renewal(NEXT, tenant_code="ipsa", current=CURRENT, observed=elsewhere)

    def test_another_customer_is_refused(self):
        with pytest.raises(RenewalRejectedError, match="ambev"):
            check_renewal(NEXT, tenant_code="ambev", current=None, observed=HERE)

    def test_an_older_licence_cannot_shorten_the_one_in_force(self):
        # Loading last quarter's file by mistake must not cut the term.
        with pytest.raises(RenewalRejectedError, match="2027-01-19"):
            check_renewal(CURRENT, tenant_code="ipsa", current=NEXT, observed=HERE)

    def test_the_same_term_for_a_new_installation_is_a_reactivation(self):
        check_renewal(CURRENT, tenant_code="ipsa", current=CURRENT, observed=HERE)

    def test_the_first_licence_of_an_installation_is_accepted(self):
        check_renewal(NEXT, tenant_code="ipsa", current=None, observed=HERE)


class TestAnswer:
    def test_a_paid_period_comes_with_its_licence(self):
        assert renewal_answer({"status": "renewed", "licence": "abc.def"}) == ("renewed", "abc.def")

    def test_an_unpaid_one_is_pending(self):
        assert renewal_answer({"status": "pending"}) == ("pending", "")

    @pytest.mark.parametrize("answer", [None, [], {}, {"status": "renewed"}, {"status": "otra"}, "texto"])
    def test_anything_else_is_an_error_never_a_licence(self, answer):
        assert renewal_answer(answer)[0] == "error"


class TestOnlineRenewal:
    def test_without_a_service_nothing_leaves(self):
        def no_network(url, payload):
            raise AssertionError("tried to reach the network")

        keys = TrustedKeys(public_key="")
        assert renew_online("ipsa", keys=keys, url="", post=no_network) == "not_configured"


class TestGrace:
    def test_thirty_days_read_only_after_the_term(self):
        assert evaluate(NEXT, today=date(2027, 5, 19)).status is LicenseStatus.GRACE
        assert evaluate(NEXT, today=date(2027, 5, 19)).read_only
        assert evaluate(NEXT, today=date(2027, 5, 20)).status is LicenseStatus.EXPIRED
