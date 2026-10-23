"""Renewal use cases: the request, loading a licence file, and the online
check (v4 Phase 3).

Loading a licence is the same whichever road it came by — a file the
administrator uploads, or the answer of our renewal service: the signature
first, then whether it applies to this customer, this installation and a term
no shorter than the one in force. Nothing restarts: the next request already
reads the new record.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from modules.licensing.domain.license import (
    TOKEN_VERSION,
    License,
    LicenseError,
    TrustedKeys,
    token_version,
    verify,
)
from modules.licensing.domain.renewal import (
    RenewalRejectedError,
    RenewalRequest,
    check_renewal,
    renewal_answer,
)

Post = Callable[[str, dict[str, Any]], object]


class RenewalUnavailableError(Exception):
    """The renewal service could not be asked, or answered nonsense."""


@dataclass(frozen=True, slots=True)
class ImportOutcome:
    status: str  # "renewed" or "already"
    license_id: str
    valid_until: date


def build_request(tenant_code: str, *, keys: TrustedKeys) -> RenewalRequest:
    from modules.licensing.infrastructure.installation import observed_installation
    from modules.licensing.infrastructure.renewal_facts import counts, program_version

    current = current_licence(tenant_code, keys=keys)
    equipment, users = counts(tenant_code)
    return RenewalRequest(
        tenant=tenant_code,
        license_id=current.license_id if current else "",
        valid_until=current.valid_until if current else None,
        installation=observed_installation(tenant_code).code(),
        version=program_version(),
        equipment=equipment,
        users=users,
    )


def current_licence(tenant_code: str, *, keys: TrustedKeys) -> License | None:
    from modules.licensing.application.license_service import latest_record

    record = latest_record(tenant_code)
    if record is None:
        return None
    try:
        return verify(record.token, keys)
    except LicenseError:
        return None


def import_licence(tenant_code: str, text: str, *, keys: TrustedKeys, source: str) -> ImportOutcome:
    from modules.licensing.application.license_service import store_licence
    from modules.licensing.infrastructure.installation import observed_installation
    from modules.licensing.infrastructure.models import LicenseRecord, Tenant

    token = token_of(text)
    if token_version(token) != TOKEN_VERSION:
        raise RenewalRejectedError("No es una licencia de PREDICTIVE en vigor (se espera la versión 2).")
    try:
        licence = verify(token, keys)
    except LicenseError as exc:
        raise RenewalRejectedError(
            "La firma de la licencia no es válida: no la emitimos nosotros, o el archivo se alteró."
        ) from exc
    tenant = Tenant.objects.filter(code=tenant_code).first()
    if tenant is None:
        raise RenewalRejectedError(f"«{tenant_code}» no está registrado en esta instalación.")
    if LicenseRecord.objects.filter(license_id=licence.license_id).exists():
        return ImportOutcome("already", licence.license_id, licence.valid_until)

    check_renewal(
        licence, tenant_code=tenant_code, current=current_licence(tenant_code, keys=keys),
        observed=observed_installation(tenant_code),
    )
    store_licence(
        tenant, licence, token, kind="renewed",
        detail=f"cargada por {source}: {licence.license_id} → {licence.valid_until}",
    )
    return ImportOutcome("renewed", licence.license_id, licence.valid_until)


def renew_online(tenant_code: str, *, keys: TrustedKeys, url: str, post: Post) -> str:
    """Without a renewal service configured, nothing leaves the network: the
    file is the only road, and the system works the same. With one, every
    question is recorded with exactly what was sent."""
    if not url:
        return "not_configured"
    request = build_request(tenant_code, keys=keys)
    try:
        status, token = renewal_answer(post(url, request.payload()))
    except RenewalUnavailableError as exc:
        _record(tenant_code, url, request, "error", str(exc))
        return "error"
    if status != "renewed":
        _record(tenant_code, url, request, status, "" if status == "pending" else "respuesta no válida")
        return status
    try:
        outcome = import_licence(tenant_code, token, keys=keys, source="renovación en línea")
    except RenewalRejectedError as exc:
        _record(tenant_code, url, request, "rejected", str(exc))
        return "rejected"
    _record(tenant_code, url, request, "renewed", f"vigente hasta {outcome.valid_until}", outcome.license_id)
    return "renewed"


def renew_all_online(*, keys: TrustedKeys, url: str, post: Post) -> dict[str, str]:
    """Only on-premise installations renew; a hosted tenant we renew ourselves."""
    from modules.licensing.infrastructure.models import Tenant

    codes = Tenant.objects.filter(deployment="on_premise", licenses__isnull=False).values_list(
        "code", flat=True
    )
    return {code: renew_online(code, keys=keys, url=url, post=post) for code in sorted(set(codes))}


def token_of(text: str) -> str:
    """A `.lic` file may carry `#` comment lines around the token."""
    lines = (line.strip() for line in text.splitlines())
    return next((line for line in lines if line and not line.startswith("#")), "")


def _record(tenant_code: str, url: str, request: RenewalRequest, outcome: str, detail: str,
            license_id: str = "") -> None:
    from modules.licensing.infrastructure.models import RenewalQuery, Tenant

    RenewalQuery.objects.create(
        tenant=Tenant.objects.get(code=tenant_code), url=url[:300], sent=request.payload(),
        outcome=outcome, detail=detail[:300], license_id=license_id,
    )
