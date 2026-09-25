"""Storing an uploaded file for an owner — a visit, a point, a train.

Files are content-addressed: the same bytes are stored once. The row is per
owner, though: the same photo attached to a second visit is a second row
pointing at the same stored object. Deduplicating the row too made the upload
answer with the first visit's photo, and the second visit never showed it.
"""

from __future__ import annotations

import io

from modules.media.domain.derivatives import Variant, storage_key
from modules.media.domain.formats import ACCEPTED, MAX_BYTES, extension_of
from modules.media.infrastructure.local_store import checksum, store
from modules.media.infrastructure.models import MediaAsset

THUMB_EDGE = 320


class UploadRejectedError(ValueError):
    pass


def store_upload(*, company_id: int, upload, kind: str, owner_type: str, owner_id: int,
                 caption: str = "", user=None) -> tuple[MediaAsset, bool]:
    """The asset for this owner, and whether it was created now."""
    if upload is None:
        raise UploadRejectedError("No llegó ningún archivo")
    if upload.size > MAX_BYTES:
        raise UploadRejectedError(f"El archivo supera los {MAX_BYTES // 1024 // 1024} MB")
    extension = extension_of(upload.name)
    if extension not in ACCEPTED:
        raise UploadRejectedError(f"Formato no aceptado: .{extension}")

    payload = upload.read()
    digest = checksum(payload)
    assets = MediaAsset.objects.for_company(company_id).filter(checksum_sha256=digest)
    mine = assets.filter(owner_type=owner_type, owner_id=owner_id).first()
    if mine is not None:
        return mine, False

    stored = assets.first()
    backend = store()
    key = stored.original_key if stored else storage_key(company_id, digest, None, extension)
    if stored is None:
        backend.put(key, payload, content_type=upload.content_type or "")

    asset = MediaAsset.objects.create(
        company_id=company_id, kind=kind, owner_type=owner_type, owner_id=owner_id,
        original_key=key, original_format=ACCEPTED[extension], original_bytes=len(payload),
        checksum_sha256=digest, caption=(caption or "").strip()[:300], uploaded_by=user,
        processing_state="pending", **_ownership(owner_type, owner_id),
    )
    if stored is not None:
        # Same bytes, same derivatives: nothing to convert again.
        asset.derivatives = stored.derivatives
        asset.width, asset.height = stored.width, stored.height
        asset.processing_state = stored.processing_state
        asset.save(update_fields=["derivatives", "width", "height", "processing_state"])
    else:
        _make_thumbnail(asset, payload, backend)
    return asset, True


def release(asset: MediaAsset) -> None:
    """Deletes the row, and the stored files only when no other row uses them."""
    shared = MediaAsset.objects.filter(
        company_id=asset.company_id, original_key=asset.original_key
    ).exclude(id=asset.id).exists()
    if not shared:
        backend = store()
        for key in [asset.original_key, *(d.get("key") for d in asset.derivatives.values())]:
            if key:
                try:
                    backend.delete(key)
                except (OSError, ValueError):
                    # The row is what the app reads; a missing file must not
                    # leave an undeletable record behind.
                    pass
    asset.delete()


def _ownership(owner_type: str, owner_id: int) -> dict:
    """The equipment an upload belongs to, worked out once and stored.

    A gallery of thousands cannot join visit → equipment on every page, and
    the answer never changes after the upload.
    """
    if not owner_id:
        return {}
    if owner_type == "visit":
        from modules.services.models import ServiceVisit

        visit = ServiceVisit.objects.filter(id=owner_id).values("equipment_id", "visited_at").first()
        if visit:
            return {"equipment_ref": visit["equipment_id"], "captured_on": visit["visited_at"].date()}
    if owner_type == "point":
        from modules.assets.models import MeasurementPoint

        point = MeasurementPoint.objects.filter(id=owner_id).values("equipment_id").first()
        if point:
            return {"equipment_ref": point["equipment_id"]}
    return {}


def _make_thumbnail(asset: MediaAsset, payload: bytes, backend) -> None:
    """A gallery must not download twenty full-size phone photos.

    Only the cheap preview is made here; the heavy conversion is the nightly
    job's work (doc 05), and a thermogram is never re-encoded because its
    temperature matrix lives in the original.
    """
    if asset.original_format in ("heic", "document", "tiff"):
        return
    try:
        from PIL import Image, ImageOps

        image = ImageOps.exif_transpose(Image.open(io.BytesIO(payload)))
        asset.width, asset.height = image.size
        image.thumbnail((THUMB_EDGE, THUMB_EDGE))
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="JPEG", quality=72)
        key = storage_key(asset.company_id, asset.checksum_sha256, Variant.THUMB, "jpg")
        backend.put(key, buffer.getvalue(), content_type="image/jpeg")
        asset.derivatives = {"thumb": {"key": key, "w": image.width, "h": image.height}}
        # Still pending: the gallery has its preview, but card and full are the
        # nightly job's work.
        asset.processing_state = "pending"
    except Exception:
        # An unreadable image still uploads; the original is what matters.
        asset.processing_state = "failed"
    asset.save(update_fields=["derivatives", "width", "height", "processing_state", "updated_at"])
