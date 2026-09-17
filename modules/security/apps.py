from django.apps import AppConfig


class SecurityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "modules.security"
    label = "security"
    verbose_name = "Usuarios y permisos"
