"""What a customer database starts from, with no books and no demo (v4 Phase 6).

    manage.py tenants run ipsa catalog base --company ipsa --name "Industrias del Papel S.A."
    manage.py tenants run ipsa modules bootstrap
    manage.py tenants run ipsa catalog admin --email ti@ipsa.com.pe --password-file -
    manage.py tenants run ipsa catalog limits      # the norms' limits, only when we choose to

`base` runs before any module is installed: the modules' install hooks look up
its rows (the rollers module asks for the unit `mm`). `admin` runs after, so
the roles have the modules' permissions to grant. All three are idempotent.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from modules.core.infrastructure.transactions import tenant_atomic
from modules.licensing.infrastructure.context import current_alias


class Command(BaseCommand):
    help = "Lay the base catalogue, the first administrator or the norms' limits"

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["base", "admin", "limits"])
        parser.add_argument("--company", default="", help="the company code (base: the one to create)")
        parser.add_argument("--name", default="", help="base: the company's name")
        parser.add_argument("--tax-id", default="", help="base: the company's RUC")
        parser.add_argument("--email", default="", help="admin: the administrator's email")
        parser.add_argument("--first-name", default="Administrador")
        parser.add_argument("--last-name", default="")
        parser.add_argument("--password-file", default="",
                            help="admin: read the password from this file ('-' is standard input)")

    @tenant_atomic
    def handle(self, *args, **options):
        getattr(self, f"_{options['action']}")(options)

    def _base(self, options):
        from modules.core.infrastructure.base_catalogue import lay_base_catalogue
        from modules.core.models import Company

        if not options["company"] or not options["name"]:
            raise CommandError("base needs --company and --name")
        company, created = Company.objects.get_or_create(
            code=options["company"],
            defaults={"name": options["name"], "tax_id": options["tax_id"]},
        )
        catalogue = lay_base_catalogue(company, using=current_alias())
        made = catalogue.made + Counter(empresa=int(created))
        self.stdout.write(self.style.SUCCESS(f"catálogo base de {company.code}: {_tally(made)}"))

    def _admin(self, options):
        from modules.core.infrastructure.base_catalogue import lay_roles
        from modules.security.models import Membership, User

        company = _company(options)
        if not options["email"] or not options["password_file"]:
            raise CommandError("admin needs --email and --password-file")
        password = _read_password(options["password_file"])
        roles, made = lay_roles(company)
        if User.objects.filter(email__iexact=options["email"]).exists():
            raise CommandError(f"ya existe un usuario {options['email']}")
        user = User.objects.create_user(
            email=options["email"], password=password, first_name=options["first_name"],
            last_name=options["last_name"], language=company.default_language,
        )
        Membership.objects.create(user=user, company=company, role=roles["company_admin"], is_default=True)
        self.stdout.write(self.style.SUCCESS(
            f"administrador {user.email} en {company.code} ({_tally(made) if made else 'roles ya estaban'})"
        ))

    def _limits(self, options):
        from modules.thresholds.infrastructure.norm_limits import MissingCatalogueError, load_norm_limits

        company = _company(options)
        try:
            created = load_norm_limits(company)
        except MissingCatalogueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"límites de norma en {company.code}: {created} nuevos"))


def _company(options):
    from modules.core.models import Company

    if options["company"]:
        company = Company.objects.filter(code=options["company"]).first()
        if company is None:
            raise CommandError(f"no hay una empresa {options['company']}: corre antes `catalog base`")
        return company
    companies = list(Company.objects.all()[:2])
    if len(companies) != 1:
        raise CommandError("--company is required: this database has " + (
            "no company yet (catalog base)" if not companies else "more than one"
        ))
    return companies[0]


def _read_password(source: str) -> str:
    text = sys.stdin.read() if source == "-" else Path(source).read_text()
    password = text.strip()
    if len(password) < 12:
        raise CommandError("la contraseña del administrador necesita al menos 12 caracteres")
    return password


def _tally(made) -> str:
    return ", ".join(f"{kind} {count}" for kind, count in sorted(made.items()) if count) or "nada nuevo"
