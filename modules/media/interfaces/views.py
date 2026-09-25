"""Uploading and listing the photographic record.

A service produces two kinds of image and they are not interchangeable: the
screen captures that *are* the measurement (spectra, thermograms, ultrasound
traces) and the photographs of the equipment in operation. Both hang off the
visit, and each keeps what it is in `kind`.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Count
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.core.infrastructure.audit import record
from modules.media.infrastructure.local_store import store
from modules.media.infrastructure.uploads import UploadRejectedError, release, store_upload
from modules.media.models import MediaAsset
from modules.security.application.access import build_actor
from modules.security.domain.policies import MediaRef, can_delete_media, can_edit_media

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
        rights = _rights(request, rows)
        return Response({
            "items": [_payload(row, backend, rights) for row in rows],
            "next_cursor": next_cursor,
        })

    def post(self, request):
        actor = build_actor(request.user, request.company_id)
        if not actor.has("media.upload"):
            raise PermissionDenied("Falta el permiso media.upload")
        try:
            asset, created = store_upload(
                company_id=request.company_id,
                upload=request.FILES.get("file"),
                kind=request.data.get("kind") or "photo",
                owner_type=request.data.get("owner_type") or "visit",
                owner_id=int(request.data.get("owner_id") or 0),
                caption=request.data.get("caption") or "",
                user=request.user,
            )
        except UploadRejectedError as cause:
            raise ValidationError(str(cause)) from cause
        return Response(_payload(asset, rights=_rights(request, [asset])), status=201 if created else 200)


class MediaDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, media_id: int):
        asset = _get(request, media_id)
        rights = _rights(request, [asset])
        if not rights[asset.id].edit:
            raise PermissionDenied("No puedes editar este archivo")
        if "caption" in request.data:
            asset.caption = (request.data.get("caption") or "").strip()[:300]
            asset.save(update_fields=["caption", "updated_at"])
        return Response(_payload(asset, rights=rights))

    def delete(self, request, media_id: int):
        asset = _get(request, media_id)
        if not _rights(request, [asset])[asset.id].delete:
            raise PermissionDenied(
                "Solo quien subió el archivo puede quitarlo, y mientras la visita siga abierta"
            )
        record(
            request, "media.deleted", object_type="media", object_id=asset.id,
            before={"kind": asset.kind, "owner_type": asset.owner_type,
                    "owner_id": asset.owner_id, "caption": asset.caption},
        )
        release(asset)
        return Response(status=204)


def _get(request, media_id: int) -> MediaAsset:
    asset = MediaAsset.objects.for_company(request.company_id).filter(id=media_id).first()
    if asset is None:
        raise ValidationError("Ese archivo no existe")
    return asset


@dataclass(frozen=True, slots=True)
class _Rights:
    edit: bool
    delete: bool


_NO_RIGHTS = _Rights(edit=False, delete=False)


def _rights(request, rows) -> dict[int, _Rights]:
    """What the current user may do with each file of a page.

    The server decides and the payload says so: the gallery used to show the
    delete button to anyone who could edit the visit, and the server then
    refused them with a 403 nobody saw.
    """
    from modules.services.infrastructure.visit_refs import visit_refs

    actor = build_actor(request.user, request.company_id)
    visits = visit_refs(
        request.company_id,
        (row.owner_id for row in rows if row.owner_type == "visit"),
    )
    rights = {}
    for row in rows:
        media = MediaRef(
            uploaded_by_id=row.uploaded_by_id,
            visit=visits.get(row.owner_id) if row.owner_type == "visit" else None,
        )
        rights[row.id] = _Rights(
            edit=can_edit_media(actor, media), delete=can_delete_media(actor, media)
        )
    return rights


def _payload(asset: MediaAsset, backend=None, rights: dict[int, _Rights] | None = None) -> dict:
    backend = backend or store()
    thumb = (asset.derivatives or {}).get("thumb", {}).get("key")
    allowed = (rights or {}).get(asset.id, _NO_RIGHTS)
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
        "can_edit": allowed.edit,
        "can_delete": allowed.delete,
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
        rights = _rights(request, rows)
        body = {
            "items": [
                {**_payload(row, backend, rights), "visit": visits.get(row.owner_id)}
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
