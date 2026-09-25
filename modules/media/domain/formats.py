"""Which files the system takes, and what each one is."""

from __future__ import annotations

ACCEPTED: dict[str, str] = {
    "jpg": "jpeg", "jpeg": "jpeg", "png": "png", "heic": "heic", "heif": "heic",
    "webp": "webp", "tif": "tiff", "tiff": "tiff", "pdf": "document",
}
IMAGE_FORMATS = frozenset({"jpeg", "png", "heic", "webp", "tiff"})
MAX_BYTES = 40 * 1024 * 1024


def extension_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def format_of(filename: str) -> str | None:
    return ACCEPTED.get(extension_of(filename))


def is_image(filename: str) -> bool:
    return format_of(filename) in IMAGE_FORMATS
