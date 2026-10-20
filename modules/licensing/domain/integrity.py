"""The signed list of every file a sealed build ships, checked at startup
(v4 Phase 5).

The manifest is `path\tsha256` lines, sorted, signed with our Ed25519 key.
At startup the program verifies the signature with the public key it already
carries (`signing_key.py`), then every file against it. A single mismatch and
it refuses to start: an altered binary is not ours to run.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path

from modules.licensing.domain.signing import SigningKeyError, verify_blob

CHUNK = 1 << 20


class IntegrityError(Exception):
    pass


def _digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(CHUNK):
            sha.update(block)
    return sha.hexdigest()


def _shipped(root: Path, patterns: Iterable[str]) -> list[Path]:
    seen: set[Path] = set()
    for pattern in patterns:
        seen.update(path for path in root.rglob(pattern) if path.is_file())
    return sorted(seen)


def build_manifest(root: Path, patterns: Iterable[str]) -> bytes:
    """Deterministic: sorted relative paths with POSIX separators."""
    lines = [f"{path.relative_to(root).as_posix()}\t{_digest(path)}" for path in _shipped(root, patterns)]
    return ("\n".join(lines) + "\n").encode()


def read_manifest(manifest: bytes) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in manifest.decode().splitlines():
        if line:
            path, _, digest = line.partition("\t")
            entries[path] = digest
    return entries


def verify_tree(root: Path, manifest: bytes, signature: bytes, public_key: str) -> None:
    """Signature first — a forged manifest must not choose what is checked —
    then every file. Names the first file that is missing or altered."""
    try:
        verify_blob(public_key, manifest, signature)
    except SigningKeyError as exc:
        raise IntegrityError(f"la firma del manifiesto de integridad no es válida: {exc}") from exc
    for path, expected in read_manifest(manifest).items():
        target = root / path
        if not target.is_file():
            raise IntegrityError(f"falta un archivo del programa: {path}")
        if _digest(target) != expected:
            raise IntegrityError(f"un archivo del programa fue alterado: {path}")
