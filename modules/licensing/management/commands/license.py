"""`manage.py license …` — the licence key and the installation it covers.

    license keygen --signing-key ~/claves/predictive-signing.pem
    license keygen --signing-key <file> --password-file <file> --public-key <file>
    license fingerprint [--tenant ipsa] [--code]
    license clock reset [--tenant ipsa]
    license request [--tenant ipsa]
    license import <file.lic> [--tenant ipsa]
    license renew [--tenant ipsa]
    license log [--tenant ipsa] [--limit 20]

keygen runs on the issuing machine. Without --public-key the public half is
installed in the program (`domain/signing_key.py`) and ships with the next
version; with it, it goes to that file instead, which is how the on-premise
bench keeps a throwaway key.

fingerprint and clock run on the customer's server. fingerprint is the first
thing support asks for, and what is sent to issue or reactivate a licence.
clock reset is the emergency way out of a clock that once jumped forward: it
forgets the remembered date, never below the licence's issue date, and leaves
an event support sees. The normal way out is a new licence.

request, import, renew and log are renewal (v4 Phase 3): the text to send us,
loading the `.lic` we send back, asking the online service now instead of
waiting for the daily check, and the record of what was sent to it.
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
        parser.add_argument(
            "action",
            choices=["keygen", "fingerprint", "clock", "request", "import", "renew", "log", "sign-manifest"],
        )
        parser.add_argument("target", nargs="?", help="clock: reset · import: the .lic file")
        parser.add_argument("--limit", type=int, default=20, help="log: how many queries")
        parser.add_argument("--signing-key", help="keygen: where the encrypted signing key goes")
        parser.add_argument("--password-file", help="keygen: read the password from this file")
        parser.add_argument("--public-key", help="keygen: write the public key here, not into the program")
        parser.add_argument("--replace", action="store_true",
                            help="keygen: replace the public key the program ships with")
        parser.add_argument("--tenant", default="", help="fingerprint, clock: the tenant (DEFAULT_TENANT)")
        parser.add_argument("--code", action="store_true", help="fingerprint: print only the code")
        parser.add_argument("--out-manifest", help="sign-manifest: where the manifest goes")
        parser.add_argument("--out-sig", help="sign-manifest: where its signature goes")

    def handle(self, *args, **options):
        if options["action"] == "clock" and options["target"] != "reset":
            raise CommandError("usage: license clock reset [--tenant <code>]")
        if options["action"] == "import" and not options["target"]:
            raise CommandError("usage: license import <file.lic> [--tenant <code>]")
        getattr(self, f"_{options['action'].replace('-', '_')}")(options)

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

    def _sign_manifest(self, options):
        """Build the signed integrity manifest of a sealed build. Run in the
        Docker builder after compiling, with the signing key as a build secret
        — the key never lands in a layer."""
        from pathlib import Path

        from modules.licensing.domain.integrity import build_manifest
        from modules.licensing.domain.signing import SigningKeyError, sign_blob
        from modules.licensing.infrastructure.signing_key_file import load_signing_key

        if not options["signing_key"]:
            raise CommandError("--signing-key is required")
        manifest = build_manifest(Path(settings.BASE_DIR), ("*.so", "*.pyc"))
        try:
            key = load_signing_key(options["signing_key"], options["password_file"])
        except SigningKeyError as exc:
            raise CommandError(str(exc)) from exc
        out_manifest = Path(options["out_manifest"] or settings.INTEGRITY_MANIFEST)
        out_sig = Path(options["out_sig"] or settings.INTEGRITY_SIGNATURE)
        out_manifest.write_bytes(manifest)
        out_sig.write_bytes(sign_blob(key, manifest))
        count = len(manifest.decode().splitlines())
        self.stdout.write(self.style.SUCCESS(f"manifiesto de {count} archivos firmado en {out_manifest}"))

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
        self.stdout.write(
            "Envía el código a Industrie Ampel para emitir o reactivar la licencia de esta instalación."
        )

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


    def _request(self, options):
        from modules.licensing.application.renewal import build_request
        from modules.licensing.domain.renewal import RenewalRejectedError
        from modules.licensing.infrastructure.keys import trusted_keys

        try:
            self.stdout.write(build_request(_tenant(options), keys=trusted_keys()).text())
        except RenewalRejectedError as exc:
            raise CommandError(str(exc)) from exc

    def _import(self, options):
        from modules.licensing.application.renewal import import_licence
        from modules.licensing.domain.renewal import RenewalRejectedError
        from modules.licensing.infrastructure.keys import trusted_keys

        try:
            text = Path(options["target"]).read_text()
            outcome = import_licence(_tenant(options), text, keys=trusted_keys(), source="license import")
        except OSError as exc:
            raise CommandError(f"no se puede leer {options['target']}: {exc.strerror}") from exc
        except RenewalRejectedError as exc:
            raise CommandError(str(exc)) from exc
        if outcome.status == "already":
            self.stdout.write(f"{outcome.license_id} ya está cargada: vigente hasta {outcome.valid_until}")
        else:
            self.stdout.write(self.style.SUCCESS(
                f"licencia {outcome.license_id} cargada: vigente hasta {outcome.valid_until}"
            ))

    def _renew(self, options):
        from modules.licensing.application.renewal import renew_online
        from modules.licensing.infrastructure.keys import trusted_keys
        from modules.licensing.infrastructure.renewal_client import post_json

        code = _tenant(options)
        outcome = renew_online(code, keys=trusted_keys(), url=settings.LICENSE_RENEW_URL, post=post_json)
        if outcome == "not_configured":
            self.stdout.write("sin LICENSE_RENEW_URL: la renovación es solo por archivo (license import)")
            return
        self.stdout.write(f"{code}: {outcome} (detalle en license log)")

    def _log(self, options):
        import json

        from modules.licensing.infrastructure.models import RenewalQuery

        queries = RenewalQuery.objects.select_related("tenant").filter(tenant__code=_tenant(options))
        for query in queries[: options["limit"]]:
            self.stdout.write(f"{query.at:%Y-%m-%d %H:%M} UTC  {query.outcome:<8} {query.url}")
            self.stdout.write(f"    enviado: {json.dumps(query.sent, ensure_ascii=False, sort_keys=True)}")
            if query.detail or query.license_id:
                self.stdout.write(f"    {query.detail} {query.license_id}".rstrip())


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
