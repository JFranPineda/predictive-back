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
    # The highest date seen under the licence in force, signed (domain/clock.py).
    # A copy lives in the installation file.
    clock = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"

    @property
    def alias(self) -> str:
        return f"tenant_{self.code}"


class Installation(models.Model):
    """This installation's identity: one row, created on first use. A copy
    lives in the data volume, so losing either one does not change it."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    installation_id = models.UUIDField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return str(self.installation_id)


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


class RenewalQuery(models.Model):
    """Every question this server asked our renewal service, with exactly
    what it sent: the customer's IT can audit what left their network."""

    OUTCOMES = [
        ("renewed", "Renovada"), ("pending", "Pendiente de pago"),
        ("rejected", "Licencia rechazada"), ("error", "Sin respuesta válida"),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="renewal_queries")
    at = models.DateTimeField(auto_now_add=True, db_index=True)
    url = models.CharField(max_length=300)
    sent = models.JSONField()
    outcome = models.CharField(max_length=10, choices=OUTCOMES)
    detail = models.CharField(max_length=300, blank=True)
    license_id = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ["-at"]

    def __str__(self) -> str:
        return f"{self.tenant.code} {self.at:%Y-%m-%d %H:%M} {self.outcome}"


class TenantExport(models.Model):
    """A full export (v4 Phase 4), prepared in the background and kept until
    the next one replaces it."""

    STATES = [("pending", "En cola"), ("running", "Preparando"), ("done", "Lista"), ("failed", "Falló")]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="exports")
    requested_by = models.CharField(max_length=254, blank=True)
    status = models.CharField(max_length=10, choices=STATES, default="pending")
    path = models.CharField(max_length=500, blank=True)
    size = models.PositiveBigIntegerField(default=0)
    rows = models.PositiveBigIntegerField(default=0)
    files = models.PositiveIntegerField(default=0)
    error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.tenant.code} {self.created_at:%Y-%m-%d %H:%M} {self.status}"


class LicenseEvent(models.Model):
    """Why a request was refused, and when. The first thing support looks at."""

    KINDS = [
        ("issued", "Emitida"), ("renewed", "Renovada"), ("revoked", "Revocada"),
        ("blocked", "Acceso bloqueado"), ("degraded", "Solo lectura"),
        ("limit_reached", "Límite alcanzado"), ("fingerprint_mismatch", "Base de datos distinta"),
        ("clock_reset", "Fecha recordada reiniciada"),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=30, choices=KINDS, db_index=True)
    detail = models.CharField(max_length=300, blank=True)
    at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-at"]
