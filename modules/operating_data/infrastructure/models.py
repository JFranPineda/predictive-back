from __future__ import annotations

from django.db import models

from modules.core.infrastructure.models import TenantModel, TranslatableModel


class OperatingParameter(TenantModel, TranslatableModel):
    """What the equipment was doing while it was measured.

    The source reports carry these beside the vibration values — frequency,
    suction and discharge pressure, running hours — and without them a reading
    cannot be compared with the one before it: 4.6 mm/s at 60 Hz and 4.6 mm/s
    at 54 Hz are not the same measurement.
    """

    code = models.SlugField(max_length=40)
    name = models.CharField(max_length=120)
    unit_code = models.CharField(max_length=20, blank=True)
    technique_code = models.SlugField(max_length=30, blank=True)
    applies_to = models.JSONField(
        default=list, blank=True, help_text="Equipment types; empty means all"
    )
    is_cumulative = models.BooleanField(
        default=False, help_text="Running hours only grow; a drop means it was reset"
    )
    decimals = models.PositiveSmallIntegerField(default=1)
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("company", "code")]
        ordering = ["order", "name"]

    def __str__(self) -> str:
        return self.name


class OperatingReading(TenantModel):
    service_visit = models.ForeignKey(
        "services.ServiceVisit", on_delete=models.CASCADE, related_name="operating_readings"
    )
    equipment = models.ForeignKey(
        "assets.Equipment", on_delete=models.CASCADE, related_name="operating_readings"
    )
    parameter = models.ForeignKey(
        OperatingParameter, on_delete=models.PROTECT, related_name="readings"
    )
    value = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    text_value = models.CharField(
        max_length=120, blank=True, help_text="For codes such as ISO 4406 cleanliness"
    )
    taken_at = models.DateTimeField(db_index=True)

    class Meta:
        unique_together = [("service_visit", "parameter")]
        indexes = [models.Index(fields=["company", "equipment", "-taken_at"])]
