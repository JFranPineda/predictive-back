from django.db import models

from modules.core.infrastructure.models import TenantModel

# Q11: the four boxes of a roller's sheet — parallelism and level, each read
# on the drive side (the reference) and on the transmission side.
BOXES = ("parallel_drive", "parallel_transmission", "level_drive", "level_transmission")


class TopographySurvey(TenantModel):
    """One topography service on a train (Q11): the sheet's frame — its date,
    the main component everything is measured from, the notes, the train's
    schema and the plan of the whole analysis with its own notes."""

    service_visit = models.OneToOneField(
        "services.ServiceVisit", on_delete=models.CASCADE, related_name="topography_survey"
    )
    asset_group = models.ForeignKey("assets.AssetGroup", on_delete=models.CASCADE, related_name="+")
    title = models.CharField(
        max_length=200, blank=True, help_text="p. ej. 'Alineamiento y nivelación prensa 1'"
    )
    survey_date = models.DateField(null=True, blank=True, help_text="Fecha del servicio")
    reference_label = models.CharField(
        max_length=80, blank=True, help_text="Componente principal de referencia, p. ej. 'Prensa 1'"
    )
    plan_number = models.CharField(max_length=60, blank=True)
    instrument = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    schema_image = models.ForeignKey(
        "media.MediaAsset", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    plan_image = models.ForeignKey(
        "media.MediaAsset", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    plan_notes = models.TextField(blank=True)
    created_by = models.ForeignKey("security.User", on_delete=models.SET_NULL, null=True, related_name="+")


class TopographyElementReading(TenantModel):
    """One roller read against the main component (Q11): its separation on
    each of the four boxes of the sheet, in mm, with the photo of each box,
    and the horizontal and vertical displacement it needs (+3 mm, -1 mm).

    `asset_group` is denormalized from the visit's equipment so a history
    query for "Rodillo 5 on this train" never has to join through the visit.
    """

    asset_group = models.ForeignKey(
        "assets.AssetGroup", on_delete=models.CASCADE, related_name="topography_readings"
    )
    service_visit = models.ForeignKey(
        "services.ServiceVisit", on_delete=models.CASCADE, related_name="topography_readings"
    )
    element_label = models.CharField(max_length=40, help_text="El polín medido, p. ej. 'Rodillo N°5'")
    reference_label = models.CharField(
        max_length=80, blank=True, help_text="Contra qué se mide; vacío = el componente principal"
    )
    parallel_drive_mm = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    parallel_transmission_mm = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    horizontal_displacement_mm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    level_drive_mm = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    level_transmission_mm = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    vertical_displacement_mm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    parallel_drive_photo = models.ForeignKey(
        "media.MediaAsset", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    parallel_transmission_photo = models.ForeignKey(
        "media.MediaAsset", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    level_drive_photo = models.ForeignKey(
        "media.MediaAsset", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    level_transmission_photo = models.ForeignKey(
        "media.MediaAsset", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    observation = models.TextField(blank=True)
    created_by = models.ForeignKey("security.User", on_delete=models.SET_NULL, null=True, related_name="+")

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self) -> str:
        return f"{self.element_label} ({self.service_visit_id})"
