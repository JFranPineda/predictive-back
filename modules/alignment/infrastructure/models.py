from __future__ import annotations

from django.db import models

from modules.core.infrastructure.models import TenantModel


class AlignmentTolerance(TenantModel):
    """One RPM tier of the SKF-style chart V3-17 judges against.

    Global rows (`asset_group` null) are the illustrative defaults every
    company starts with; a row with `asset_group` set overrides them for that
    one train, because a company's own laser-alignment procedure can be
    stricter than the generic chart.
    """

    asset_group = models.ForeignKey(
        "assets.AssetGroup", on_delete=models.CASCADE, null=True, blank=True,
        related_name="alignment_tolerances",
        help_text="Vacío: tolerancia global por RPM. Con conjunto: la sobrescribe.",
    )
    # The norma whose scale this tier is (Q10): the SKF chart is one norma, a
    # client's own procedure another, and each record says which it used.
    standard = models.ForeignKey(
        "thresholds.ThresholdStandard", on_delete=models.CASCADE, null=True, blank=True,
        related_name="alignment_tiers",
    )
    rpm_ceiling = models.PositiveIntegerField(
        null=True, blank=True, help_text="RPM por debajo de la cual aplica; vacío = sin techo"
    )
    parallel_mm = models.DecimalField(max_digits=6, decimal_places=3)
    angular_mm_per_100mm = models.DecimalField(max_digits=6, decimal_places=3)

    class Meta:
        ordering = ["asset_group_id", models.F("rpm_ceiling").asc(nulls_last=True)]

    def __str__(self) -> str:
        scope = self.asset_group.name if self.asset_group_id else "global"
        ceiling = f"<{self.rpm_ceiling} rpm" if self.rpm_ceiling else "sin techo"
        return f"{scope} · {ceiling}"


class AlignmentRecord(TenantModel):
    """One laser alignment: before, after, and the tolerance it was judged
    with — frozen at save time, exactly like a `Reading` freezes its
    threshold set. A tolerance edited later must never rewrite what a report
    already told the customer (AC-05).
    """

    asset_group = models.ForeignKey(
        "assets.AssetGroup", on_delete=models.PROTECT, related_name="alignment_records"
    )
    service_visit = models.ForeignKey(
        "services.ServiceVisit", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="alignment_records",
    )
    driver_label = models.CharField(max_length=80, blank=True, help_text="El motriz del acople")
    driven_label = models.CharField(max_length=80, blank=True, help_text="El conducido del acople")
    rpm = models.DecimalField(max_digits=8, decimal_places=1)
    instrument = models.CharField(max_length=120, blank=True)

    before_angular_h = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    before_parallel_h = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    before_angular_v = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    before_parallel_v = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)

    after_angular_h = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    after_parallel_h = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    after_angular_v = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    after_parallel_v = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)

    backlash_within_tolerance = models.BooleanField(null=True, blank=True)
    notes = models.TextField(blank=True)

    # Frozen with the record, like `Reading.threshold_set`: a tolerance
    # changed next year must not silently repaint last year's ✓/✗.
    tolerance_parallel_mm = models.DecimalField(max_digits=6, decimal_places=3)
    tolerance_angular_mm_per_100mm = models.DecimalField(max_digits=6, decimal_places=3)
    # The norma the tolerance came from, chosen per report (Q10).
    standard = models.ForeignKey(
        "thresholds.ThresholdStandard", on_delete=models.PROTECT, null=True, blank=True,
        related_name="alignment_records",
    )

    # Linked, never duplicated: the maintenance intervention this measurement
    # belongs to lives in its own module (V3-32); this is only the reading.
    diagnosed_fault = models.ForeignKey(
        "diagnostics.FaultMode", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    created_by = models.ForeignKey(
        "security.User", on_delete=models.SET_NULL, null=True, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.asset_group.name} · {self.created_at:%Y-%m-%d}"
