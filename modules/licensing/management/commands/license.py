"""`manage.py license …` — the licence key and the installation it covers.

    license keygen --signing-key ~/claves/predictive-signing.pem
    license keygen --signing-key <file> --password-file <file> --public-key <file>
    license fingerprint [--tenant ipsa] [--code]
    license clock reset [--tenant ipsa]

keygen runs on the issuing machine. Without --public-key the public half is
installed in the program (`domain/signing_key.py`) and ships with the next
version; with it, it goes to that file instead, which is how the on-premise
bench keeps a throwaway key.

fingerprint and clock run on the customer's server. fingerprint is the first
thing support asks for, and what is sent to issue or reactivate a licence.
clock reset is the emergency way out of a clock that once jumped forward: it
forgets the remembered date, never below the licence's issue date, and leaves
an event support sees. The normal way out is a new licence.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from modules.licensing.domain import signing_key as shipped
from modules.licensing.domain.clock import ClockReference
from modules.licensing.domain.license import LicenseError, verify
from modules.licensing.domain.signing import (
    SigningKeyError,
    encrypt_signing_key,
    generate_signing_key,
    public_key_text,
)
from modules.licensing.infrastructure.signing_key_file import read_password, write_signing_key


class Command(BaseCommand):
    help = "Licence key pair, installation fingerprint and remembered date"

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["keygen", "fingerprint", "clock"])
        parser.add_argument("subaction", nargs="?", choices=["reset"])
        parser.add_argument("--signing-key", help="keygen: where the encrypted signing key goes")
        parser.add_argument("--password-file", help="keygen: read the password from this file")
        parser.add_argument("--public-key", help="keygen: write the public key here, not into the program")
        parser.add_argument("--replace", action="store_true",
                            help="keygen: replace the public key the program ships with")
        parser.add_argument("--tenant", default="", help="fingerprint, clock: the tenant (DEFAULT_TENANT)")
        parser.add_argument("--code", action="store_true", help="fingerprint: print only the code")

    def handle(self, *args, **options):
        if options["action"] == "clock" and options["subaction"] != "reset":
            raise CommandError("usage: license clock reset [--tenant <code>]")
        getattr(self, f"_{options['action']}")(options)

    def _keygen(self, options):
        if not options["signing_key"]:
            raise CommandError("--signing-key is required")
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

    def _fingerprint(self, options):
        from modules.licensing.infrastructure.installation import observed_installation

        fingerprint = observed_installation(_tenant(options))
        if options["code"]:
            self.stdout.write(fingerprint.code())
            return
        pg = fingerprint.pg_system_id or "no disponible (no es PostgreSQL, o sin acceso)"
        machine = fingerprint.machine_id or f"no disponible ({settings.MACHINE_ID_FILE})"
        self.stdout.write(f"instalación  {fingerprint.installation_id}")
        self.stdout.write(f"PostgreSQL   {pg}")
        self.stdout.write(f"máquina      {machine}")
        self.stdout.write(f"código       {fingerprint.code()}")
        self.stdout.write("Envía el código a 1A-MIG para emitir o reactivar la licencia de esta instalación.")

    def _clock(self, options):
        from modules.licensing.application.license_service import latest_record
        from modules.licensing.infrastructure.clock_store import (
            load_reference,
            reading_baseline,
            store_reference,
        )
        from modules.licensing.infrastructure.context import ensure_registered
        from modules.licensing.infrastructure.installation import installation_id
        from modules.licensing.infrastructure.keys import trusted_keys
        from modules.licensing.infrastructure.models import LicenseEvent, Tenant

        code = _tenant(options)
        tenant = Tenant.objects.filter(code=code).first()
        record = latest_record(code)
        if tenant is None or record is None:
            raise CommandError(f"'{code}' no tiene licencia")
        try:
            license_ = verify(record.token, trusted_keys())
        except LicenseError as exc:
            raise CommandError(f"la licencia vigente no verifica: {exc}") from exc

        installation = installation_id()
        before = load_reference(tenant, license_id=license_.license_id, installation_id=installation)
        now = datetime.now(UTC)
        store_reference(
            tenant,
            ClockReference(license_.license_id, now, reading_baseline(ensure_registered(code))),
            installation_id=installation,
        )
        detail = f"{before.seen_at:%Y-%m-%d %H:%M} → " if before else "sin fecha → "
        detail += f"{now:%Y-%m-%d %H:%M} UTC"
        LicenseEvent.objects.create(tenant=tenant, kind="clock_reset", detail=detail)
        self.stdout.write(self.style.WARNING(f"fecha recordada de '{code}' reiniciada: {detail}"))


def _tenant(options) -> str:
    code = options["tenant"] or settings.DEFAULT_TENANT
    if not code:
        raise CommandError("--tenant is required (no DEFAULT_TENANT)")
    from modules.licensing.application.tenant_resolver import UnknownTenant, resolve

    try:
        resolve(code)
    except UnknownTenant as exc:
        raise CommandError(f"unknown tenant '{code}'") from exc
    return code


def _install(public: str) -> None:
    source = Path(shipped.__file__)
    text, count = re.subn(r'^PUBLIC_KEY = ".*"$', f'PUBLIC_KEY = "{public}"', source.read_text(), flags=re.M)
    if count != 1:
        raise CommandError(f"{source} no tiene una línea PUBLIC_KEY que reemplazar")
    source.write_text(text)
