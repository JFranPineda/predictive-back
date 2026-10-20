from __future__ import annotations

from django.conf import settings

from modules.licensing.domain.license import TrustedKeys


def trusted_keys() -> TrustedKeys:
    """What this installation verifies licences with: the public key shipped
    in the program, and nothing else (v1 HMAC retired, v4 Phase 5)."""
    return TrustedKeys(public_key=settings.LICENSE_PUBLIC_KEY)
