"""The signing key on disk: an encrypted file that only its owner reads, on
the issuing machine. No installation ever has one."""

from __future__ import annotations

import getpass
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from modules.licensing.domain.signing import SigningKeyError, decrypt_signing_key


def read_password(password_file: str | None, *, confirm: bool = False) -> str:
    """From a file for scripts (its first line), else asked at the terminal."""
    if password_file:
        try:
            lines = Path(password_file).expanduser().read_text().splitlines()
        except OSError as exc:
            raise SigningKeyError(f"no se puede leer {password_file}: {exc.strerror}") from exc
        return lines[0] if lines else ""
    password = getpass.getpass("Contraseña de la clave de firma: ")
    if confirm and getpass.getpass("Repítela: ") != password:
        raise SigningKeyError("las contraseñas no coinciden")
    return password


def load_signing_key(path: str, password_file: str | None) -> Ed25519PrivateKey:
    try:
        pem = Path(path).expanduser().read_bytes()
    except OSError as exc:
        raise SigningKeyError(f"no se puede leer la clave de firma {path}: {exc.strerror}") from exc
    return decrypt_signing_key(pem, read_password(password_file))


def write_signing_key(path: str, pem: bytes) -> Path:
    """Never over an existing file: the public key already shipped would be
    left without the half that signs for it."""
    target = Path(path).expanduser()
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise SigningKeyError(f"{target} ya existe: una clave de firma no se reemplaza") from exc
    except OSError as exc:
        raise SigningKeyError(f"no se puede escribir {target}: {exc.strerror}") from exc
    with os.fdopen(fd, "wb") as handle:
        handle.write(pem)
    return target
