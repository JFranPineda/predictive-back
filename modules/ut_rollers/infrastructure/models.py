from django.db import models

from modules.core.infrastructure.models import TenantModel

SIDES = (("drive", "Lado mando"), ("transmission", "Lado transmisión"))


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
    # Q15: on a press roller's journal, which side it was found on; empty on
    # a dryer's shell. `length_mm` is where along the journal ("a 219.8 mm
    # de longitud").
    side = models.CharField(max_length=15, choices=SIDES, blank=True)
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


class JournalInspection(TenantModel):
    """One journal of one press roller, on one side, in one order (Q15): the
    detail table's row — diameter, external and total length — and whether
    it could be reached. What was found on it are its indications."""

    ACCESS = (("ok", "Con acceso"), ("covered", "Tapado (sin acceso)"), ("no_access", "Sin acceso"))

    service_order = models.ForeignKey("services.ServiceOrder", on_delete=models.CASCADE, related_name="+")
    equipment = models.ForeignKey("assets.Equipment", on_delete=models.CASCADE, related_name="ut_journals")
    side = models.CharField(max_length=15, choices=SIDES)
    diameter_mm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    external_length_mm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    total_length_mm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    access = models.CharField(max_length=15, choices=ACCESS, default="ok")
    access_note = models.CharField(max_length=200, blank=True, help_text="Por qué no hubo acceso")
    # Empty: the state is written from the access and the findings.
    state_text = models.TextField(blank=True)
    created_by = models.ForeignKey("security.User", on_delete=models.SET_NULL, null=True, related_name="+")

    class Meta:
        unique_together = [("service_order", "equipment", "side")]
        ordering = ["equipment__order_in_group", "side"]


class RollerGroupReport(TenantModel):
    """What the report says about one group in one order (Q15): conclusions,
    recommendations, the group's plan and its photographic record (media
    owned by it)."""

    service_order = models.ForeignKey("services.ServiceOrder", on_delete=models.CASCADE, related_name="+")
    asset_group = models.ForeignKey("assets.AssetGroup", on_delete=models.CASCADE, related_name="+")
    conclusions = models.TextField(blank=True)
    recommendations = models.TextField(blank=True)
    plan_image = models.ForeignKey(
        "media.MediaAsset", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_by = models.ForeignKey("security.User", on_delete=models.SET_NULL, null=True, related_name="+")

    class Meta:
        unique_together = [("service_order", "asset_group")]
