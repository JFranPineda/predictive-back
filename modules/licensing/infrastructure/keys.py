from __future__ import annotations

from django.conf import settings

from modules.licensing.domain.license import TrustedKeys


def trusted_keys() -> TrustedKeys:
    """What this installation verifies licences with: the public key, and the
    v1 secret only where one is still configured."""
    return TrustedKeys(public_key=settings.LICENSE_PUBLIC_KEY, legacy_secret=settings.LICENSE_SECRET)
