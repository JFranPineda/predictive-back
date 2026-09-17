"""Filesystem storage for deployments without object storage.

Production signs URLs and lets the browser talk to S3 directly (doc 05). A
single-server install, and every developer machine, has no MinIO running, and
"the photo feature only works if you also run object storage" is not a real
feature. Both backends answer the same two questions: where does this byte
live, and what URL serves it.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from django.conf import settings


class LocalObjectStore:
    def __init__(self) -> None:
        self._root = Path(settings.MEDIA_ROOT)

    def put(self, key: str, payload: bytes, content_type: str = "") -> None:
        del content_type
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def url(self, key: str) -> str:
        return f"{settings.MEDIA_URL}{key}"

    def _path(self, key: str) -> Path:
        # A key is built by us from a checksum, never from a filename, so it
        # cannot climb out of MEDIA_ROOT — but the check costs nothing.
        candidate = (self._root / key).resolve()
        if not str(candidate).startswith(str(self._root.resolve())):
            raise ValueError(f"key escapes the media root: {key}")
        return candidate


def checksum(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def store():
    """The store this deployment uses."""
    if settings.MEDIA_BACKEND == "s3":
        from modules.media.infrastructure.storage import ObjectStore

        return ObjectStore()
    return LocalObjectStore()
