"""The two halves of the key that signs licences.

The signing half stays on our issuing machine, in a file encrypted with a
password: a stolen copy is useless without it. The public half ships with the
program (`signing_key.py`) and is all a verifier ever holds.

The file is a standard encrypted PKCS#8 PEM, so `openssl pkey -in <file>` can
inspect it. Its key derivation (PBKDF2-SHA256, 2048 rounds) is cryptography's
fixed choice for that format, which is why the password has a floor: the
password carries the weight, not the derivation.
"""

from __future__ import annotations

import base64

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

MIN_PASSWORD_LENGTH = 16


class SigningKeyError(Exception):
    pass


def generate_signing_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def public_key_text(signing_key: Ed25519PrivateKey) -> str:
    raw = signing_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def load_public_key(text: str) -> Ed25519PublicKey:
    try:
        return Ed25519PublicKey.from_public_bytes(base64.b64decode(text, validate=True))
    except ValueError as exc:
        raise SigningKeyError("no hay una clave pública Ed25519 válida instalada") from exc


def encrypt_signing_key(signing_key: Ed25519PrivateKey, password: str) -> bytes:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise SigningKeyError(f"la contraseña necesita al menos {MIN_PASSWORD_LENGTH} caracteres")
    return signing_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(password.encode()),
    )


def decrypt_signing_key(pem: bytes, password: str) -> Ed25519PrivateKey:
    try:
        key = serialization.load_pem_private_key(pem, password=password.encode())
    except TypeError as exc:
        # cryptography's way of saying the file was never encrypted.
        raise SigningKeyError("el archivo de la clave de firma no está cifrado: no se usa") from exc
    except ValueError as exc:
        raise SigningKeyError("contraseña incorrecta, o el archivo no es una clave de firma") from exc
    except UnsupportedAlgorithm as exc:
        raise SigningKeyError("el archivo no es una clave Ed25519") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise SigningKeyError("el archivo no es una clave Ed25519")
    return key
