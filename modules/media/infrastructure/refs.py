"""An image as a screen needs it: where to open it and its thumbnail."""

from __future__ import annotations


def image_ref(asset) -> dict | None:
    if asset is None:
        return None
    from modules.media.infrastructure.local_store import store

    backend = store()
    thumb = (asset.derivatives or {}).get("thumb", {}).get("key")
    return {
        "id": asset.id,
        "kind": asset.kind,
        "caption": asset.caption,
        "url": backend.url(asset.original_key),
        "thumb_url": backend.url(thumb) if thumb else None,
    }
