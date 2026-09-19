"""Turning an original into the derivatives the gallery serves.

This is the work doc 05 calls the nightly conversion. It lives here, not in a
Celery task, for two reasons: a single-server install has no broker, and a job
that only exists as a task is a job nobody can re-run when it fails. The task
and the `media_convert` command are both thin callers of `convert_one`.

Encoding degrades gracefully. AVIF is what the requirement asks for, but the
plugin is an optional dependency and a deployment without it must still get a
gallery — WebP is half the win and always available, and a derivative that
does not exist costs the browser the whole original.
"""

from __future__ import annotations

import io
import logging

from django.db.models import Q
from django.utils import timezone

from modules.media.domain.derivatives import (
    OriginalFormat,
    Variant,
    specs_for,
    storage_key,
)
from modules.media.domain.flir import extract as extract_flir
from modules.media.infrastructure.local_store import store
from modules.media.infrastructure.models import MediaAsset

logger = logging.getLogger(__name__)

# Formats whose original is a document, not an image: nothing to resize.
NON_IMAGE = frozenset({"document"})


def convert_pending(limit: int = 500, *, retry_failed: bool = False) -> dict:
    """Converts everything waiting. Returns a small report, not a log line."""

    states = Q(processing_state="pending")
    if retry_failed:
        states |= Q(processing_state="failed")
    queryset = MediaAsset.objects.filter(states).order_by("created_at")
    report = {"converted": 0, "skipped": 0, "failed": 0}
    for asset_id in list(queryset.values_list("id", flat=True)[:limit]):
        outcome = convert_one(asset_id)
        report[outcome] = report.get(outcome, 0) + 1
    return report


def convert_one(media_id: int) -> str:
    """One asset, start to finish. Never raises: one bad file is not a night."""

    asset = MediaAsset.objects.filter(id=media_id).first()
    if asset is None:
        return "skipped"
    if asset.original_format in NON_IMAGE:
        MediaAsset.objects.filter(id=media_id).update(
            processing_state="done", updated_at=timezone.now()
        )
        return "skipped"

    MediaAsset.objects.filter(id=media_id).update(processing_state="processing")
    backend = store()
    try:
        payload = backend.get(asset.original_key)
    except (OSError, ValueError):
        logger.warning("media %s has no original at %s", media_id, asset.original_key)
        MediaAsset.objects.filter(id=media_id).update(processing_state="failed")
        return "failed"

    fields = ["processing_state", "updated_at"]
    try:
        # The radiometric payload is read before anything touches the pixels,
        # and its failure is a note on the asset, never the end of the job.
        if asset.kind == "thermogram":
            asset.thermal_meta = _radiometric(payload, asset, backend)
            fields.append("thermal_meta")

        image = _open(payload, asset.original_format)
        asset.width, asset.height = image.size
        asset.exif = asset.exif or _read_exif(image)
        asset.derivatives = {
            **(asset.derivatives or {}),
            **_derivatives(image, asset, backend),
        }
        asset.processing_state = "done"
        fields += ["width", "height", "exif", "derivatives"]
    except Exception as cause:  # noqa: BLE001 - the report says what happened
        logger.exception("media %s failed to convert", media_id)
        asset.processing_state = "failed"
        asset.thermal_meta = {**(asset.thermal_meta or {}), "error": str(cause)[:200]}
        fields.append("thermal_meta")
        asset.save(update_fields=sorted(set(fields)))
        return "failed"

    asset.save(update_fields=sorted(set(fields)))
    return "converted"


def _derivatives(image, asset: MediaAsset, backend) -> dict:
    fmt = _encoder()
    made = {}
    for spec in specs_for(OriginalFormat(_known_format(asset.original_format))):
        resized = _resize(image, spec.max_edge)
        key = storage_key(asset.company_id, asset.checksum_sha256, spec.variant, fmt)
        backend.put(key, _encode(resized, fmt, spec.quality), content_type=f"image/{fmt}")
        made[spec.variant.value] = {"key": key, "w": resized.width, "h": resized.height}
    return made


def _radiometric(payload: bytes, asset: MediaAsset, backend) -> dict:
    """Stores the raw sensor grid beside the original and keeps its constants.

    Without this a thermogram stops being a measurement and becomes a picture
    of one: ΔT against a similar component cannot be recomputed from pixels.
    """
    result = extract_flir(payload)
    meta = {
        "radiometric": result.is_radiometric,
        "notes": result.notes,
        "width": result.width,
        "height": result.height,
    }
    if result.calibration is not None:
        meta["calibration"] = result.calibration.as_dict()
    if result.raw_thermal is not None:
        key = storage_key(
            asset.company_id, asset.checksum_sha256, None,
            f"thermal.{result.raw_format}",
        )
        backend.put(key, result.raw_thermal, content_type="application/octet-stream")
        meta["raw_key"] = key
        meta["raw_format"] = result.raw_format
    return meta


def _known_format(value: str) -> str:
    try:
        OriginalFormat(value)
    except ValueError:
        return OriginalFormat.JPEG.value
    return value


def _encoder() -> str:
    """The best format this deployment can actually write."""

    try:
        import pillow_avif  # noqa: F401
    except ImportError:
        return "webp"
    return "avif"


def _open(payload: bytes, fmt: str):
    from PIL import Image

    if fmt == "heic":
        import pillow_heif

        pillow_heif.register_heif_opener()
    return Image.open(io.BytesIO(payload))


def _resize(image, max_edge: int):
    from PIL import ImageOps

    copy = ImageOps.exif_transpose(image)
    copy.thumbnail((max_edge, max_edge))
    return copy


def _encode(image, fmt: str, quality: int) -> bytes:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format=fmt.upper(), quality=quality)
    return buffer.getvalue()


def _read_exif(image) -> dict:
    raw = getattr(image, "getexif", lambda: {})() or {}
    return {str(key): str(value)[:120] for key, value in dict(raw).items()}


__all__ = ["Variant", "convert_one", "convert_pending"]
