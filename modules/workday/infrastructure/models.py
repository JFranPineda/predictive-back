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


class SafetyPermit(TenantModel):
    """An ATS (Análisis de Trabajo Seguro): the safety permit a technician
    opens before touching a train (F3-04). The signed copy is a media asset
    owned by it; without that copy the permit does not count."""

    workday = models.ForeignKey(Workday, on_delete=models.CASCADE, related_name="permits")
    asset_group = models.ForeignKey("assets.AssetGroup", on_delete=models.PROTECT, related_name="+")
    number = models.CharField(max_length=40)
    document = models.ForeignKey(
        "media.MediaAsset", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_by = models.ForeignKey("security.User", on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

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
