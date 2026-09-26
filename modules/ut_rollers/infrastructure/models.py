from django.db import models

from modules.core.infrastructure.models import TenantModel


class UTIndication(TenantModel):
    """A defect found on a roller: a crack or an undercut, sized and placed.

    The order's thickness grid says how worn a roller is; the Word report next
    to it says what is actually wrong with it. Its photo is an ordinary media
    asset owned by the indication (`owner_type="ut_indication"`).
    """

    KINDS = (("crack", "Fisura"), ("undercut", "Socavación"), ("other", "Otra"))

    equipment = models.ForeignKey(
        "assets.Equipment", on_delete=models.CASCADE, related_name="ut_indications"
    )
    service_visit = models.ForeignKey(
        "services.ServiceVisit", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ut_indications",
    )
    kind = models.CharField(max_length=20, choices=KINDS)
    length_mm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    depth_mm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    position = models.CharField(max_length=120, blank=True, help_text='e.g. "P3, lado mando"')
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        "security.User", on_delete=models.SET_NULL, null=True, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} · {self.equipment_id}"
