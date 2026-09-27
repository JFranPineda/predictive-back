"""`manage.py history archive|list` — the logs older than the screens' window.

Run it per tenant, nightly:

    manage.py tenants run ambev history archive

It repeats until nothing is left to file, so the first run on a table nobody
ever pruned finishes in one go.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from modules.core.infrastructure.history import archive, folder, sources
from modules.core.infrastructure.models import Company, HistoryFile


class Command(BaseCommand):
    help = "File the part of each log that the screens no longer show"

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["archive", "list"])
        parser.add_argument("--company", default="", help="Company code; every company by default")

    def handle(self, *args, **options):
        companies = Company.objects.all()
        if options["company"]:
            companies = companies.filter(code=options["company"])
        for company in companies:
            getattr(self, f"_{options['action']}")(company)

    def _archive(self, company) -> None:
        for source in sources():
            filed = 0
            while True:
                result = archive(company, source)
                filed += result["archived"]
                if result["archived"] == 0 or result["pending"] == 0:
                    break
            self.stdout.write(f"{company.code} {source.code}: {filed} filas archivadas")
            if filed:
                self.stdout.write(f"  → {folder(company, source)}")

    def _list(self, company) -> None:
        for source in sources():
            self.stdout.write(f"{company.code} {source.code} — {folder(company, source)}")
            rows = HistoryFile.objects.for_company(company.id).filter(source=source.code)
            for stored in rows:
                self.stdout.write(f"  {stored.period}  {stored.rows:>8} filas  {stored.size:>9} bytes")
