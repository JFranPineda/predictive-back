"""`manage.py license …` — the key that signs licences, on the issuing machine.

    license keygen --signing-key ~/claves/predictive-signing.pem
    license keygen --signing-key <file> --password-file <file> --public-key <file>

Without --public-key the public half is installed in the program
(`domain/signing_key.py`) and ships with the next version; with it, it goes to
that file instead, which is how the on-premise bench keeps a throwaway key.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from modules.licensing.domain import signing_key as shipped
from modules.licensing.domain.signing import (
    SigningKeyError,
    encrypt_signing_key,
    generate_signing_key,
    public_key_text,
)
from modules.licensing.infrastructure.signing_key_file import read_password, write_signing_key


class Command(BaseCommand):
    help = "Generate the licence signing key pair"

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["keygen"])
        parser.add_argument("--signing-key", required=True, help="where the encrypted signing key goes")
        parser.add_argument("--password-file", help="read the password from this file instead of asking")
        parser.add_argument("--public-key", help="write the public key here instead of into the program")
        parser.add_argument("--replace", action="store_true",
                            help="replace the public key the program ships with")

    def handle(self, *args, **options):
        installing = not options["public_key"]
        if installing and shipped.PUBLIC_KEY and not options["replace"]:
            raise CommandError(
                "el programa ya trae una clave pública: reemplazarla deja sin verificar toda "
                "licencia emitida con la actual. Usa --replace si es lo que quieres."
            )
        try:
            key = generate_signing_key()
            pem = encrypt_signing_key(key, read_password(options["password_file"], confirm=True))
            path = write_signing_key(options["signing_key"], pem)
        except SigningKeyError as exc:
            raise CommandError(str(exc)) from exc

        public = public_key_text(key)
        if installing:
            _install(public)
            where = f"instalada en {Path(shipped.__file__).name}: viaja con la próxima versión"
        else:
            Path(options["public_key"]).write_text(public + "\n")
            where = f"escrita en {options['public_key']}"
        self.stdout.write(self.style.SUCCESS(f"clave de firma cifrada en {path}"))
        self.stdout.write(f"clave pública {public} — {where}")


def _install(public: str) -> None:
    source = Path(shipped.__file__)
    text, count = re.subn(r'^PUBLIC_KEY = ".*"$', f'PUBLIC_KEY = "{public}"', source.read_text(), flags=re.M)
    if count != 1:
        raise CommandError(f"{source} no tiene una línea PUBLIC_KEY que reemplazar")
    source.write_text(text)
