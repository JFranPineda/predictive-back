from __future__ import annotations

from dataclasses import dataclass

from modules.core.domain.errors import DomainError

MAX_ORIGINAL_BYTES = 80 * 1024 * 1024


class UploadTooLarge(DomainError):
    code = "upload_too_large"


class UnsupportedFormat(DomainError):
    code = "unsupported_format"


@dataclass(frozen=True, slots=True)
class UploadRequest:
    filename: str
    size_bytes: int
    checksum_sha256: str
    kind: str
    owner_type: str
    owner_id: int
    captured_at: str | None = None


@dataclass(frozen=True, slots=True)
class UploadTicket:
    """`skip=True` means the byte-identical file is already stored: the client
    must not upload it again. In the field the same photo gets re-sent more
    often than anyone expects."""

    media_id: int
    upload_url: str | None
    skip: bool
    storage_key: str


def validate(request: UploadRequest, allowed_formats: frozenset[str]) -> None:
    if request.size_bytes > MAX_ORIGINAL_BYTES:
        raise UploadTooLarge(f"{request.filename} is {request.size_bytes} bytes")
    extension = request.filename.rsplit(".", 1)[-1].lower() if "." in request.filename else ""
    if extension not in allowed_formats:
        raise UnsupportedFormat(f"'{extension}' is not accepted")
