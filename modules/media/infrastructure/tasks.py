"""The nightly conversion required by R4 — plus the reason it cannot be the
only thing that runs.

A crew uploading at 10:00 needs its gallery at 10:01, so upload time produces a
cheap 320px preview and the expensive work — full derivatives, EXIF,
radiometric extraction — happens at 00:15 when nobody is waiting.

The work itself lives in `conversion`, so the same code runs from a worker, a
cron line or `manage.py media_convert` on a box with no broker at all.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from modules.media.domain.derivatives import OriginalFormat, keeps_pristine_original
from modules.media.infrastructure.conversion import convert_one, convert_pending
from modules.media.infrastructure.models import MediaAsset

logger = logging.getLogger(__name__)


@shared_task(name="media.convert_pending")
def convert_pending_task(limit: int = 5000) -> dict:
    """Fan out; one task per asset so a single bad file cannot stall a night."""
    pending = MediaAsset.objects.filter(processing_state="pending").values_list(
        "id", flat=True
    )[:limit]
    for media_id in pending:
        convert_media.delay(media_id)
    return {"queued": len(pending)}


@shared_task(name="media.convert_media")
def convert_media(media_id: int) -> str:
    return convert_one(media_id)


@shared_task(name="media.convert_inline")
def convert_inline(limit: int = 500) -> dict:
    """For deployments with a beat but no media queue worth fanning out to."""
    return convert_pending(limit)


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
