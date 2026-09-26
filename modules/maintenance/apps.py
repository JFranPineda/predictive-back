from django.apps import AppConfig


class MaintenanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "modules.maintenance"
    label = "maintenance"
    verbose_name = "Mantenimiento correctivo"
