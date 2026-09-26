"""Images inside a PDF are embedded, not linked.

A PDF is read offline and forwarded by e-mail: a `/media/...` link would
point at nothing. Each image is read from the store, reduced to what a
printed page needs, and inlined as a data URI.
"""

from __future__ import annotations

import base64
import io
from functools import cache
from pathlib import Path

MAX_EDGE = 1100


@cache
def logo() -> str:
    """The provider's logo (V3-33): the same on every tenant's reports."""
    payload = (Path(__file__).parent / "brand" / "1a-mig.jpeg").read_bytes()
    return "data:image/jpeg;base64," + base64.b64encode(payload).decode()


def embedded(asset) -> str | None:
    """A media asset as a JPEG data URI, or None when it is not a picture
    (a lab PDF) or its bytes are gone."""
    if asset is None:
        return None
    from modules.media.infrastructure.local_store import store

    try:
        payload = store().get(asset.original_key)
    except (OSError, ValueError):
        return None
    try:
        from PIL import Image, ImageOps

        try:
            from pillow_heif import register_heif_opener

            register_heif_opener()
        except ImportError:
            pass
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(payload)))
        image.thumbnail((MAX_EDGE, MAX_EDGE))
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="JPEG", quality=80)
    except Exception:
        # A picture that will not open is left out of the report, not fatal to it.
        return None
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
