"""The nightly conversion required by R4 — plus the reason it cannot be the
only thing that runs.

A crew uploading at 10:00 needs its gallery at 10:01, so upload time produces a
cheap 256px preview (client-side when the browser can) and the expensive work —
full derivatives, EXIF, radiometric extraction, perceptual hash — happens at
00:15 when nobody is waiting.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from modules.media.domain.derivatives import OriginalFormat, keeps_pristine_original, specs_for, storage_key
from modules.media.infrastructure.models import MediaAsset

logger = logging.getLogger(__name__)

BATCH_SIZE = 50


@shared_task(name="media.convert_pending")
def convert_pending() -> int:
    """Fan out; one task per asset so a single bad file cannot stall a night."""
    pending = MediaAsset.objects.filter(processing_state="pending").values_list("id", flat=True)[:5000]
    for media_id in pending:
        convert_media.delay(media_id)
    return len(pending)


@shared_task(name="media.convert_media", bind=True, max_retries=3, default_retry_delay=300)
def convert_media(self, media_id: int) -> None:
    from modules.media.infrastructure.storage import ObjectStore

    asset = MediaAsset.objects.filter(id=media_id).first()
    if asset is None or asset.processing_state == "done":
        return

    MediaAsset.objects.filter(id=media_id).update(processing_state="processing")
    store = ObjectStore()
    fmt = OriginalFormat(asset.original_format)

    try:
        payload = store.get(asset.original_key)
        if fmt is OriginalFormat.RADIOMETRIC_JPEG:
            asset.thermal_meta = _extract_radiometric(payload, asset, store)

        image = _open(payload, fmt)
        asset.width, asset.height = image.size
        asset.exif = asset.exif or _read_exif(image)

        derivatives = {}
        for spec in specs_for(fmt):
            resized = _resize(image, spec.max_edge)
            key = storage_key(asset.company_id, asset.checksum_sha256, spec.variant, spec.fmt)
            store.put(key, _encode(resized, spec), content_type=f"image/{spec.fmt}")
            derivatives[spec.variant.value] = {"key": key, "w": resized.width, "h": resized.height}

        asset.derivatives = derivatives
        asset.processing_state = "done"
        asset.save(update_fields=["derivatives", "thermal_meta", "width", "height", "exif",
                                  "processing_state", "updated_at"])
    except Exception as exc:
        logger.exception("media %s failed to convert", media_id)
        MediaAsset.objects.filter(id=media_id).update(processing_state="failed")
        raise self.retry(exc=exc) from exc


@shared_task(name="media.prune_originals")
def prune_originals(days: int = 30) -> int:
    """Originals are never deleted — they are the dataset the vision model will
    need — but they do move to a colder storage class."""
    from modules.media.infrastructure.storage import ObjectStore

    cutoff = timezone.now() - timezone.timedelta(days=days)
    store = ObjectStore()
    moved = 0
    candidates = MediaAsset.objects.filter(processing_state="done", created_at__lt=cutoff)
    for asset in candidates.iterator(chunk_size=500):
        if keeps_pristine_original(OriginalFormat(asset.original_format)):
            continue
        store.transition(asset.original_key, storage_class="STANDARD_IA")
        moved += 1
    return moved


def _open(payload: bytes, fmt: OriginalFormat):
    import io

    from PIL import Image

    if fmt is OriginalFormat.HEIC:
        import pillow_heif

        pillow_heif.register_heif_opener()
    return Image.open(io.BytesIO(payload))


def _resize(image, max_edge: int):
    from PIL import ImageOps

    copy = ImageOps.exif_transpose(image)
    copy.thumbnail((max_edge, max_edge))
    return copy


def _encode(image, spec) -> bytes:
    import io

    import pillow_avif  # noqa: F401  registers the AVIF plugin

    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format=spec.fmt.upper(), quality=spec.quality)
    return buffer.getvalue()


def _read_exif(image) -> dict:
    raw = getattr(image, "getexif", lambda: {})() or {}
    return {str(k): str(v) for k, v in dict(raw).items()}


def _extract_radiometric(payload: bytes, asset: MediaAsset, store) -> dict:
    """Pull the temperature matrix out to Parquet before anything touches the
    pixels. Without this a thermogram stops being a measurement."""
    raise NotImplementedError("wire flirimageextractor in the thermography module")
