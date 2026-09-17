from __future__ import annotations

from django.db import models

from modules.core.infrastructure.models import TimeStampedModel


class Tenant(TimeStampedModel):
    """A customer installation, in our control plane.

    This table is the only thing that lives in *our* database when the customer
    runs their data on premise. It holds where their database is and what they
    are entitled to — never their maintenance data.
    """

    DEPLOYMENTS = [
        ("hosted", "Alojado por nosotros"),
        ("on_premise", "Base de datos del cliente"),
    ]

    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=160)
    deployment = models.CharField(max_length=20, choices=DEPLOYMENTS, default="hosted")
    # Credentials for the customer's database. Encrypted at rest in production
    # (see settings.SECRET_BOX_KEY); an env var overrides it entirely, which is
    # how the first tenant is bootstrapped before this table exists.
    database_url = models.TextField(blank=True)
    database_fingerprint = models.CharField(max_length=64, blank=True, db_index=True)
    contact_email = models.EmailField(blank=True)
    is_suspended = models.BooleanField(default=False)
    suspended_reason = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"

    @property
    def alias(self) -> str:
        return f"tenant_{self.code}"


class LicenseRecord(TimeStampedModel):
    """An issued key. The token is the signed artefact; these columns exist so
    support can answer "until when" without decoding anything."""

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="licenses")
    license_id = models.CharField(max_length=40, unique=True)
    token = models.TextField()
    plan = models.CharField(max_length=40)
    issued_at = models.DateField()
    valid_until = models.DateField(db_index=True)
    grace_days = models.PositiveSmallIntegerField(default=15)
    modules = models.JSONField(default=list, blank=True)
    limits = models.JSONField(default=dict, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-valid_until"]

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None


class LicenseEvent(models.Model):
    """Why a request was refused, and when. The first thing support looks at."""

    KINDS = [
        ("issued", "Emitida"), ("renewed", "Renovada"), ("revoked", "Revocada"),
        ("blocked", "Acceso bloqueado"), ("degraded", "Solo lectura"),
        ("limit_reached", "Límite alcanzado"), ("fingerprint_mismatch", "Base de datos distinta"),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=30, choices=KINDS, db_index=True)
    detail = models.CharField(max_length=300, blank=True)
    at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-at"]
