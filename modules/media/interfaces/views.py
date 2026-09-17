"""Uploading and listing the photographic record.

A service produces two kinds of image and they are not interchangeable: the
screen captures that *are* the measurement (spectra, thermograms, ultrasound
traces) and the photographs of the equipment in operation. Both hang off the
visit, and each keeps what it is in `kind`.
"""

from __future__ import annotations

import io

from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.media.domain.derivatives import Variant, storage_key
from modules.media.infrastructure.local_store import checksum, store
from modules.media.models import MediaAsset
from modules.security.application.access import build_actor

ACCEPTED = {
    "jpg": "jpeg", "jpeg": "jpeg", "png": "png", "heic": "heic", "heif": "heic",
    "webp": "webp", "tif": "tiff", "tiff": "tiff", "pdf": "document",
}
MAX_BYTES = 40 * 1024 * 1024
THUMB_EDGE = 320


class MediaCollectionView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        owner_type = request.query_params.get("owner_type")
        owner_id = request.query_params.get("owner_id")
        queryset = MediaAsset.objects.for_company(request.company_id).order_by("-created_at")
        if owner_type and owner_id:
            queryset = queryset.filter(owner_type=owner_type, owner_id=owner_id)
        if request.query_params.get("kind"):
            queryset = queryset.filter(kind=request.query_params["kind"])
        return Response([_payload(row) for row in queryset[:200]])

    def post(self, request):
        actor = build_actor(request.user, request.company_id)
        if not actor.has("media.upload"):
            raise PermissionDenied("Falta el permiso media.upload")

        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError("No llegó ningún archivo")
        if upload.size > MAX_BYTES:
            raise ValidationError(f"El archivo supera los {MAX_BYTES // 1024 // 1024} MB")

        extension = (upload.name.rsplit(".", 1)[-1] if "." in upload.name else "").lower()
        if extension not in ACCEPTED:
            raise ValidationError(f"Formato no aceptado: .{extension}")

        payload = upload.read()
        digest = checksum(payload)
        # Deduplicated by content: the same photo re-sent from the field costs
        # nothing and does not clutter the gallery twice.
        existing = MediaAsset.objects.for_company(request.company_id).filter(
            checksum_sha256=digest
        ).first()
        if existing is not None:
            return Response(_payload(existing), status=200)

        backend = store()
        key = storage_key(request.company_id, digest, None, extension)
        backend.put(key, payload, content_type=upload.content_type or "")

        asset = MediaAsset.objects.create(
            company_id=request.company_id,
            kind=request.data.get("kind") or "photo",
            owner_type=request.data.get("owner_type") or "visit",
            owner_id=int(request.data.get("owner_id") or 0),
            original_key=key,
            original_format=ACCEPTED[extension],
            original_bytes=len(payload),
            checksum_sha256=digest,
            caption=(request.data.get("caption") or "").strip()[:300],
            uploaded_by=request.user,
            processing_state="pending",
        )
        _make_thumbnail(asset, payload, backend)
        return Response(_payload(asset), status=201)


class MediaDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, media_id: int):
        asset = _get(request, media_id)
        if "caption" in request.data:
            asset.caption = (request.data.get("caption") or "").strip()[:300]
            asset.save(update_fields=["caption", "updated_at"])
        return Response(_payload(asset))

    def delete(self, request, media_id: int):
        actor = build_actor(request.user, request.company_id)
        if not actor.has("media.delete"):
            raise PermissionDenied("Falta el permiso media.delete")
        asset = _get(request, media_id)
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
        return Response(status=204)


def _get(request, media_id: int) -> MediaAsset:
    asset = MediaAsset.objects.for_company(request.company_id).filter(id=media_id).first()
    if asset is None:
        raise ValidationError("Ese archivo no existe")
    return asset


def _make_thumbnail(asset: MediaAsset, payload: bytes, backend) -> None:
    """A gallery must not download twenty full-size phone photos.

    Only the cheap preview is made here; the heavy conversion is the nightly
    job's work (doc 05), and a thermogram is never re-encoded because its
    temperature matrix lives in the original.
    """
    if asset.original_format in ("heic", "document", "tiff"):
        asset.processing_state = "pending"
        asset.save(update_fields=["processing_state"])
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
        asset.processing_state = "done"
    except Exception:
        # An unreadable image still uploads; the original is what matters.
        asset.processing_state = "failed"
    asset.save(update_fields=["derivatives", "width", "height", "processing_state", "updated_at"])


def _payload(asset: MediaAsset) -> dict:
    backend = store()
    thumb = (asset.derivatives or {}).get("thumb", {}).get("key")
    return {
        "id": asset.id,
        "kind": asset.kind,
        "owner_type": asset.owner_type,
        "owner_id": asset.owner_id,
        "caption": asset.caption,
        "url": backend.url(asset.original_key) if hasattr(backend, "url") else "",
        "thumb_url": backend.url(thumb) if thumb and hasattr(backend, "url") else None,
        "format": asset.original_format,
        "bytes": asset.original_bytes,
        "width": asset.width,
        "height": asset.height,
        "state": asset.processing_state,
        "uploaded_by": asset.uploaded_by.get_full_name() if asset.uploaded_by else "",
        "created_at": asset.created_at.isoformat(),
    }
