from django.apps import AppConfig


class ThermographyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "modules.thermography"
    label = "thermography"
    verbose_name = "Análisis de termografía"
