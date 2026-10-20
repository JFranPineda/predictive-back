"""The startup integrity gate (v4 Phase 5).

A sealed image ships a signed manifest of every file it carries. Before the
app serves anything, it verifies the manifest with the public key it already
holds and every file against it. An altered binary is not ours to run, so the
process refuses to start — the second belt after the deploy-time cosign check.

A source checkout has no manifest, so this does nothing there.
"""

from __future__ import annotations

import sys

from django.conf import settings

from modules.licensing.domain.integrity import IntegrityError, verify_tree


def enforce_integrity() -> None:
    manifest = settings.INTEGRITY_MANIFEST
    signature = settings.INTEGRITY_SIGNATURE
    if not manifest.is_file():
        return
    try:
        verify_tree(
            settings.BASE_DIR,
            manifest.read_bytes(),
            signature.read_bytes() if signature.is_file() else b"",
            settings.LICENSE_PUBLIC_KEY,
        )
    except (IntegrityError, OSError) as exc:
        # Nobody to raise to usefully at import time; say why and stop the
        # process so a tampered build never serves.
        sys.stderr.write(
            f"\nPREDICTIVE no puede arrancar: la verificación de integridad falló.\n  {exc}\n"
            "Reinstala la imagen firmada que te entregamos; si persiste, contacta con 1A-MIG.\n\n"
        )
        raise SystemExit(70) from exc
