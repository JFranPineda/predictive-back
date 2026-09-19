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

from django.db.models import Count

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
PAGE_SIZE = 60
MAX_PAGE_SIZE = 200
# exif, thermal_meta and geo are fat JSON columns nothing in a grid reads.
GRID_DEFER = ("exif", "thermal_meta", "geo")


class MediaCollectionView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        owner_type = request.query_params.get("owner_type")
        owner_id = request.query_params.get("owner_id")
        queryset = (
            MediaAsset.objects.for_company(request.company_id)
            .select_related("uploaded_by")
            .defer(*GRID_DEFER)
            .order_by("-created_at", "-id")
        )
        if owner_type and owner_id:
            queryset = queryset.filter(owner_type=owner_type, owner_id=owner_id)
        if request.query_params.get("kind"):
            queryset = queryset.filter(kind=request.query_params["kind"])
        rows, next_cursor = _page(queryset, request)
        backend = store()
        return Response({
            "items": [_payload(row, backend) for row in rows],
            "next_cursor": next_cursor,
        })

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
            **_ownership(request.data.get("owner_type") or "visit",
                         int(request.data.get("owner_id") or 0)),
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
        # Still pending: the gallery has its preview, but card and full are the
        # nightly job's work. Marking it done here is what left every asset
        # with a single 320px derivative and nothing else.
        asset.processing_state = "pending"
    except Exception:
        # An unreadable image still uploads; the original is what matters.
        asset.processing_state = "failed"
    asset.save(update_fields=["derivatives", "width", "height", "processing_state", "updated_at"])


def _payload(asset: MediaAsset, backend=None) -> dict:
    backend = backend or store()
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


def _ownership(owner_type: str, owner_id: int) -> dict:
    """The equipment an upload belongs to, worked out once and stored.

    A gallery of thousands cannot join visit → equipment on every page, and
    the answer never changes after the upload.
    """
    if owner_type != "visit" or not owner_id:
        return {}
    from modules.services.models import ServiceVisit

    visit = (
        ServiceVisit.objects.filter(id=owner_id)
        .values("equipment_id", "visited_at")
        .first()
    )
    if visit is None:
        return {}
    return {
        "equipment_ref": visit["equipment_id"],
        "captured_on": visit["visited_at"].date(),
    }


def _page(queryset, request) -> tuple[list, str | None]:
    """Keyset pagination on (created_at, id).

    `OFFSET 5000` makes the database walk five thousand rows it will throw
    away; a cursor turns every page into the same indexed seek, which is what
    keeps page 90 of a machine's history as fast as page 1.
    """
    limit = min(int(request.query_params.get("limit") or PAGE_SIZE), MAX_PAGE_SIZE)
    cursor = request.query_params.get("cursor")
    if cursor:
        moment, _, last_id = cursor.partition("|")
        queryset = queryset.filter(created_at__lte=moment).exclude(
            created_at=moment, id__gte=int(last_id or 0)
        )
    rows = list(queryset[: limit + 1])
    if len(rows) <= limit:
        return rows, None
    tail = rows[limit - 1]
    return rows[:limit], f"{tail.created_at.isoformat()}|{tail.id}"


class EquipmentMediaView(APIView):
    """Every image of one machine, newest first, across all its visits.

    This is the view the manifest promised and nobody could open: to see a
    year of spectra of one gearbox you had to walk its visits one by one.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, equipment_id: int):
        queryset = (
            MediaAsset.objects.for_company(request.company_id)
            .filter(equipment_ref=equipment_id)
            .select_related("uploaded_by")
            .defer(*GRID_DEFER)
            .order_by("-created_at", "-id")
        )
        if request.query_params.get("kind"):
            queryset = queryset.filter(kind=request.query_params["kind"])
        if request.query_params.get("visit"):
            queryset = queryset.filter(
                owner_type="visit", owner_id=int(request.query_params["visit"])
            )

        rows, next_cursor = _page(queryset, request)
        backend = store()
        visits = _visits_of(rows)
        body = {
            "items": [
                {**_payload(row, backend), "visit": visits.get(row.owner_id)}
                for row in rows
            ],
            "next_cursor": next_cursor,
        }
        # Counts are for the filter chips and only make sense on the first
        # page; running them on every scroll would undo the paging.
        if not request.query_params.get("cursor"):
            body["counts"] = _counts(request.company_id, equipment_id)
        return Response(body)


def _counts(company_id: int, equipment_id: int) -> dict:
    rows = (
        MediaAsset.objects.for_company(company_id)
        .filter(equipment_ref=equipment_id)
        .values("kind")
        .annotate(total=Count("id"))
    )
    return {row["kind"]: row["total"] for row in rows}


def _visits_of(rows) -> dict:
    """One query for the whole page, never one per tile."""

    ids = {row.owner_id for row in rows if row.owner_type == "visit" and row.owner_id}
    if not ids:
        return {}
    from modules.services.models import ServiceVisit

    return {
        visit["id"]: {
            "id": visit["id"],
            "visited_at": visit["visited_at"].isoformat(),
            "order_code": visit["service_order__code"],
            "technique": visit["service_order__technique__code"],
        }
        for visit in ServiceVisit.objects.filter(id__in=ids).values(
            "id", "visited_at", "service_order__code", "service_order__technique__code"
        )
    }
