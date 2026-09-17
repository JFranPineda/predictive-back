"""`manage.py modules list|install|uninstall|upgrade|bootstrap` — the CLI half
of T2. The API half lives in core.interfaces.views."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from modules.core.domain.errors import DomainError
from modules.core.interfaces.views import build_installer


class Command(BaseCommand):
    help = "Inspect and change module installation state"

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["list", "install", "uninstall", "upgrade", "bootstrap"])
        parser.add_argument("code", nargs="?")

    def handle(self, *args, **options):
        installer = build_installer()
        action = options["action"]
        code = options.get("code")

        if action == "list":
            for info in installer.catalog():
                flag = {"installed": "✓", "uninstalled": "·", "to_upgrade": "↑"}.get(info.state, "?")
                missing = f"  missing: {', '.join(info.missing_depends)}" if info.missing_depends else ""
                self.stdout.write(f"{flag} {info.manifest.code:<16} {info.manifest.version:<8} "
                                  f"{info.manifest.name}{missing}")
            return

        if action == "bootstrap":
            done = installer.install_auto_modules()
            self.stdout.write(self.style.SUCCESS(f"installed: {', '.join(done) or 'nothing to do'}"))
            return

        if not code:
            raise CommandError(f"'{action}' needs a module code")
        try:
            result = getattr(installer, action)(code)
        except DomainError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"{action}: {result or code}"))
