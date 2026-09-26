from django.db import models

from modules.core.infrastructure.models import TenantModel


class TopographyElementReading(TenantModel):
    """One row of the topography table: a plant element (a roller, a base)
    read off the machine's plan, on one visit.

    `asset_group` is denormalized from the visit's equipment so a history
    query for "R3 on this train" never has to join through the visit.
    """

    asset_group = models.ForeignKey(
        "assets.AssetGroup", on_delete=models.CASCADE, related_name="topography_readings"
    )
    service_visit = models.ForeignKey(
        "services.ServiceVisit", on_delete=models.CASCADE, related_name="topography_readings"
    )
    element_label = models.CharField(max_length=40, help_text="Su número en el plano, p. ej. 'R3'")
    level_h = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    level_v = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    parallel_h = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    parallel_v = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    observation = models.TextField(blank=True)
    created_by = models.ForeignKey(
        "security.User", on_delete=models.SET_NULL, null=True, related_name="+"
    )

    class Meta:
        ordering = ["element_label"]

    def __str__(self) -> str:
        return f"{self.element_label} ({self.service_visit_id})"
