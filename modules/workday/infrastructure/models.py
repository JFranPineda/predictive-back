from django.db import models

from modules.core.infrastructure.models import TenantModel


class Workday(TenantModel):
    """One plant's working day, opened and closed by the chief engineer
    (F3-01). Its close is what freezes the day's data for technicians."""

    plant = models.ForeignKey("assets.Plant", on_delete=models.PROTECT, related_name="workdays")
    date = models.DateField(db_index=True)
    opened_at = models.DateTimeField()
    opened_by = models.ForeignKey("security.User", on_delete=models.SET_NULL, null=True, related_name="+")
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        "security.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = [("plant", "date")]
        ordering = ["-date", "plant_id"]

    @property
    def is_open(self) -> bool:
        return self.closed_at is None


class ServiceJob(TenantModel):
    """A service (Q17): one job the staff does on one train within a workday
    — an alignment, a UT inspection, a topography survey — with its own ATS
    (Análisis de Trabajo Seguro), the three signatures that start it and the
    chief engineer's signed close that sets its final hour (Q19).

    Until it starts, the guard keeps every field of that train shut.
    """

    RISK_CATEGORIES = (("high", "Alto"), ("medium", "Mediano"), ("low", "Bajo"))

    workday = models.ForeignKey(Workday, on_delete=models.CASCADE, related_name="jobs")
    asset_group = models.ForeignKey("assets.AssetGroup", on_delete=models.PROTECT, related_name="+")
    service_order = models.ForeignKey(
        "services.ServiceOrder", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    # The ATS header, as the client's format prints it.
    activity = models.CharField(max_length=200, blank=True, help_text="Nombre de la actividad y/o trabajo")
    holder = models.CharField(max_length=160, blank=True, help_text="Titular de la actividad")
    unit = models.CharField(max_length=120, blank=True)
    area = models.CharField(max_length=120, blank=True)
    zone = models.CharField(max_length=120, blank=True)
    risk_category = models.CharField(max_length=10, choices=RISK_CATEGORIES, blank=True)
    ppe = models.TextField(blank=True, help_text="EPP")
    tools = models.TextField(blank=True, help_text="Equipos y herramientas")
    # [{step, hazard, risk, level: A|M|B, score, controls}], one row per hazard.
    steps = models.JSONField(default=list, blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    unlocked_by = models.ForeignKey(
        "security.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    unlocked_at = models.DateTimeField(null=True, blank=True)
    unlock_reason = models.TextField(blank=True)
    # The service's final hour: the moment its close was signed (Q19).
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        "security.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_by = models.ForeignKey("security.User", on_delete=models.SET_NULL, null=True, related_name="+")

    class Meta:
        ordering = ["created_at", "id"]

    @property
    def is_closed(self) -> bool:
        return self.closed_at is not None


class JobSignature(TenantModel):
    """One signature on a service: the three that start it, or one of the
    crew's on its ATS. The drawing is a media asset; a crew member is listed
    before signing, so the drawing and its time may still be empty."""

    ROLES = (
        ("production_engineer", "Ingeniero de producción"),
        ("service_leader", "Líder encargado del servicio"),
        ("plant_supervisor", "Supervisor de planta"),
        ("crew", "Personal ejecutor"),
    )

    job = models.ForeignKey(ServiceJob, on_delete=models.CASCADE, related_name="signatures")
    role = models.CharField(max_length=30, choices=ROLES)
    name = models.CharField(max_length=160)
    position = models.CharField(max_length=120, blank=True, help_text="Cargo")
    user = models.ForeignKey(
        "security.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    image = models.ForeignKey(
        "media.MediaAsset", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    signed_at = models.DateTimeField(null=True, blank=True)
    captured_by = models.ForeignKey(
        "security.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["created_at", "id"]


class FieldObservation(TenantModel):
    """What the technician did, with the photo taken first and whether the
    finding shows in it (F3-05)."""

    workday = models.ForeignKey(Workday, on_delete=models.CASCADE, related_name="observations")
    asset_group = models.ForeignKey("assets.AssetGroup", on_delete=models.PROTECT, related_name="+")
    photo = models.ForeignKey(
        "media.MediaAsset", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    visible = models.BooleanField()
    text = models.TextField()
    created_by = models.ForeignKey("security.User", on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
