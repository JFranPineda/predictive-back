from django.apps import AppConfig


class LicensingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "modules.licensing"
    label = "licensing"
    verbose_name = "Licencias y clientes"

    def ready(self):
        # A sealed image verifies its own files before serving (v4 Phase 5);
        # a source checkout has no manifest and this returns at once.
        from modules.licensing.infrastructure.integrity_check import enforce_integrity

        enforce_integrity()
