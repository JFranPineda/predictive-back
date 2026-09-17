"""`manage.py tenants …` — the control plane from the shell.

    tenants list
    tenants add ambev "AMBEV Perú" --url postgres://… --deployment on_premise
    tenants migrate ambev
    tenants issue ambev --plan enterprise --months 12 --equipment 600
    tenants revoke ambev --reason "contrato terminado"
    tenants run ambev <command> [args…]
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import UTC, date, datetime

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from modules.licensing.application.tenant_resolver import resolve
from modules.licensing.domain.license import (
    License,
    LicenseLimits,
    database_fingerprint,
    issue,
)
from modules.licensing.infrastructure.context import use_tenant
from modules.licensing.infrastructure.models import LicenseEvent, LicenseRecord, Tenant


class Command(BaseCommand):
    help = "Manage customer installations and their licences"

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["list", "add", "migrate", "issue", "revoke", "run"])
        parser.add_argument("code", nargs="?")
        parser.add_argument("name", nargs="?")
        # `run` forwards the inner command's own flags, so its tail must be
        # REMAINDER. Every other action needs argparse to keep parsing, or
        # `tenants add … --url …` would have its url swallowed as an extra.
        forwarding = "run" in sys.argv
        parser.add_argument("extra", nargs=argparse.REMAINDER if forwarding else "*")
        parser.add_argument("--url", default="")
        parser.add_argument("--deployment", default="hosted", choices=["hosted", "on_premise"])
        parser.add_argument("--plan", default="enterprise")
        parser.add_argument("--months", type=int, default=12)
        parser.add_argument("--grace", type=int, default=15)
        parser.add_argument("--equipment", type=int)
        parser.add_argument("--plants", type=int)
        parser.add_argument("--users", type=int)
        parser.add_argument("--modules", default="")
        parser.add_argument("--reason", default="")

    def handle(self, *args, **options):
        getattr(self, f"_{options['action']}")(options)

    def _list(self, options):
        for tenant in Tenant.objects.all():
            # Same ordering the enforcement path uses, or the listing shows a
            # revoked licence while the API is happily serving the new one.
            latest = tenant.licenses.order_by("-valid_until", "-created_at").first()
            licence = (
                f"{latest.plan} hasta {latest.valid_until}"
                + (" (REVOCADA)" if latest.is_revoked else "")
                if latest
                else "sin licencia"
            )
            flag = "⛔" if tenant.is_suspended else "✓"
            self.stdout.write(f"{flag} {tenant.code:<14} {tenant.deployment:<12} {licence}")

    def _add(self, options):
        code, name = self._require(options, need_name=True)
        url = options["url"]
        if not url:
            raise CommandError("--url is required (a DATABASE_URL for the customer database)")
        config_name, host = _describe(url)
        tenant, created = Tenant.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "database_url": url,
                "deployment": options["deployment"],
                "database_fingerprint": database_fingerprint(
                    tenant_code=code, database_name=config_name, host=host
                ),
            },
        )
        self.stdout.write(self.style.SUCCESS(f"{'creado' if created else 'actualizado'}: {tenant}"))

    def _migrate(self, options):
        code, _ = self._require(options)
        resolve(code)
        with use_tenant(code) as alias:
            call_command("migrate", database=alias, interactive=False)
        self.stdout.write(self.style.SUCCESS(f"migrado: {code}"))

    def _issue(self, options):
        code, _ = self._require(options)
        tenant = Tenant.objects.filter(code=code).first()
        if tenant is None:
            raise CommandError(f"unknown tenant '{code}'")

        today = date.today()
        until = _add_months(today, options["months"])
        license_ = License(
            tenant_code=code,
            plan=options["plan"],
            issued_at=today,
            valid_until=until,
            license_id=f"lic-{uuid.uuid4().hex[:12]}",
            grace_days=options["grace"],
            limits=LicenseLimits(
                max_plants=options["plants"],
                max_equipment=options["equipment"],
                max_users=options["users"],
            ),
            modules=tuple(filter(None, options["modules"].split(","))),
            database_fingerprint=tenant.database_fingerprint,
        )
        token = issue(license_, settings.LICENSE_SECRET)
        LicenseRecord.objects.create(
            tenant=tenant, license_id=license_.license_id, token=token, plan=license_.plan,
            issued_at=today, valid_until=until, grace_days=license_.grace_days,
            modules=list(license_.modules),
            limits={
                "max_plants": options["plants"],
                "max_equipment": options["equipment"],
                "max_users": options["users"],
            },
        )
        LicenseEvent.objects.create(tenant=tenant, kind="issued", detail=f"{license_.plan} → {until}")
        self.stdout.write(self.style.SUCCESS(f"licencia {license_.license_id} válida hasta {until}"))
        self.stdout.write(token)

    def _revoke(self, options):
        code, _ = self._require(options)
        record = LicenseRecord.objects.filter(tenant__code=code, revoked_at__isnull=True).first()
        if record is None:
            raise CommandError(f"no active licence for '{code}'")
        record.revoked_at = datetime.now(UTC)
        record.revoked_reason = options["reason"]
        record.save(update_fields=["revoked_at", "revoked_reason"])
        LicenseEvent.objects.create(tenant=record.tenant, kind="revoked", detail=options["reason"])
        self.stdout.write(self.style.WARNING(f"revocada: {record.license_id}"))

    def _run(self, options):
        """Runs any management command against one customer database."""
        code, name = self._require(options, need_name=True)
        resolve(code)
        with use_tenant(code):
            call_command(name, *options["extra"])

    def _require(self, options, need_name: bool = False):
        code = options.get("code")
        if not code:
            raise CommandError("a tenant code is required")
        name = options.get("name")
        if need_name and not name:
            raise CommandError("a name is required")
        return code, name


def _describe(url: str) -> tuple[str, str]:
    from modules.core.domain.database_url import parse

    config = parse(url)
    return config.name, config.host


def _add_months(start: date, months: int) -> date:
    month = start.month - 1 + months
    year = start.year + month // 12
    month = month % 12 + 1
    day = min(start.day, [31, 29 if year % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)
