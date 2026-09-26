"""What a derivative is, and which ones an original deserves (R4).

Phone originals are HEIC (iPhone, high-efficiency Android) or JPEG. A 3-5 MB
HEIC becomes a ~150-250 KB AVIF at 1024px and a ~20 KB thumbnail: the gallery
gets ~95% lighter, which is the whole point of the requirement.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Variant(StrEnum):
    THUMB = "thumb"
    CARD = "card"
    FULL = "full"


class OriginalFormat(StrEnum):
    HEIC = "heic"
    JPEG = "jpeg"
    PNG = "png"
    TIFF = "tiff"
    DNG = "dng"
    RADIOMETRIC_JPEG = "radiometric_jpeg"


@dataclass(frozen=True, slots=True)
class DerivativeSpec:
    variant: Variant
    max_edge: int
    quality: int
    fmt: str = "avif"


SPECS: tuple[DerivativeSpec, ...] = (
    DerivativeSpec(Variant.THUMB, max_edge=256, quality=60),
    DerivativeSpec(Variant.CARD, max_edge=1024, quality=55),
    DerivativeSpec(Variant.FULL, max_edge=2048, quality=50),
)

# A radiometric thermogram carries the temperature matrix in vendor metadata.
# Re-encoding it destroys the data and leaves a pretty picture, so its original
# is never degraded and never moved to cold storage.
LOSSLESS_ORIGINALS = frozenset({OriginalFormat.RADIOMETRIC_JPEG, OriginalFormat.TIFF, OriginalFormat.DNG})


def specs_for(fmt: OriginalFormat) -> tuple[DerivativeSpec, ...]:
    return SPECS


def keeps_pristine_original(fmt: OriginalFormat) -> bool:
    return fmt in LOSSLESS_ORIGINALS


def storage_key(owner: str | int, checksum: str, variant: Variant | None, extension: str) -> str:
    """Content-addressed: the same photo uploaded twice lands on one key, which
    is what makes deduplication free.

    `owner` is the tenant and company (`ipsa/1`). A company id alone is not
    unique across tenants — each customer database numbers its own from 1 —
    so two tenants shared a folder, and deleting a photo in one removed the
    other's copy of the same bytes."""
    prefix = "originals" if variant is None else f"derivatives/{variant.value}"
    return f"{prefix}/{owner}/{checksum[:2]}/{checksum}.{extension}"
