"""Runs the conversion the nightly job would run.

A single-server install has no Redis, and a customer whose thumbnails depend
on a broker being up does not have thumbnails. One cron line does the same
work: `manage.py tenants run <code> media_convert`.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from modules.media.infrastructure.conversion import convert_one, convert_pending


class Command(BaseCommand):
    help = "Builds the derivatives of every media asset still waiting"

    def add_arguments(self, parser) -> None:
        parser.add_argument("--limit", type=int, default=500)
        parser.add_argument("--retry-failed", action="store_true")
        parser.add_argument("--id", type=int, help="Convert only this asset")

    def handle(self, *args, **options) -> None:
        if options["id"]:
            outcome = convert_one(options["id"])
            self.stdout.write(f"{options['id']}: {outcome}")
            return
        report = convert_pending(options["limit"], retry_failed=options["retry_failed"])
        self.stdout.write(
            f"converted {report['converted']} · skipped {report['skipped']} "
            f"· failed {report['failed']}"
        )
