from __future__ import annotations

from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TranslatableModel(models.Model):
    """Catalogue rows carry their own translations.

    `name` holds the source text; `translations` holds {"en": "...", "es": "..."}
    for anything a user reads. A company adding its own status from the UI gets
    the same mechanism the shipped ones use.
    """

    translations = models.JSONField(default=dict, blank=True)

    class Meta:
        abstract = True

    def translated(self, field: str, language: str) -> str:
        from modules.core.domain.i18n import TranslatedText

        stored = self.translations.get(field) if isinstance(self.translations, dict) else None
        if stored:
            return TranslatedText.of(stored).get(language)
        return str(getattr(self, field, "") or "")


class Company(TimeStampedModel):
    """Tenant root. Every other row in the system hangs off one of these."""

    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=160)
    tax_id = models.CharField(max_length=40, blank=True)
    timezone = models.CharField(max_length=64, default="America/Lima")
    default_language = models.CharField(max_length=5, default="es", choices=[("es", "Español"), ("en", "English")])
    is_active = models.BooleanField(default=True)
    settings = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name_plural = "companies"

    def __str__(self) -> str:
        return self.name


class TenantQuerySet(models.QuerySet):
    def for_company(self, company_id: int) -> TenantQuerySet:
        return self.filter(company_id=company_id)


class TenantModel(TimeStampedModel):
    """Base for tenant-scoped models. Row-level security in Postgres is the
    second barrier; this manager is the first."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="+")

    objects = TenantQuerySet.as_manager()

    class Meta:
        abstract = True


class InstalledModule(TimeStampedModel):
    STATE_CHOICES = [
        ("uninstalled", "Uninstalled"),
        ("installed", "Installed"),
        ("to_upgrade", "To upgrade"),
        ("broken", "Broken"),
    ]

    code = models.SlugField(max_length=60, unique=True)
    state = models.CharField(max_length=20, choices=STATE_CHOICES, default="uninstalled")
    installed_version = models.CharField(max_length=20, blank=True, default="")
    installed_at = models.DateTimeField(null=True, blank=True)
    settings = models.JSONField(default=dict, blank=True)

    def __str__(self) -> str:
        return f"{self.code} ({self.state})"


class AuditLog(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, null=True, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=80, db_index=True)
    object_type = models.CharField(max_length=80, blank=True)
    object_id = models.CharField(max_length=40, blank=True)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["object_type", "object_id"])]
