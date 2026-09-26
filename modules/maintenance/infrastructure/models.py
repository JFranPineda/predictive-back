from django.db import models

from modules.core.infrastructure.models import TenantModel


class WorkRecord(TenantModel):
    """What a technician actually did to a train (V3-32).

    A visit measures; this records the intervention that followed — the
    "before" a vibration reading needs to prove the "after" against. Closing
    without an end time or a responsible makes the record useless for that
    comparison, so both are enforced at close, not at every save.
    """

    WORK_TYPES = (
        ("bearing_change", "Cambio de rodamiento"),
        ("alignment", "Alineamiento"),
        ("balancing", "Balanceo"),
        ("other", "Otro"),
    )

    asset_group = models.ForeignKey(
        "assets.AssetGroup", on_delete=models.PROTECT, related_name="work_records"
    )
    equipment = models.ForeignKey(
        "assets.Equipment", on_delete=models.SET_NULL, null=True, blank=True, related_name="work_records"
    )
    work_types = models.JSONField(default=list, help_text="One or more of WORK_TYPES's codes")
    other_description = models.CharField(max_length=200, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    # The day this counts against once Fase 3's daily close-out exists
    # (`10-phase-3.md`) — stored from day one so nothing needs backfilling.
    shift_date = models.DateField()
    description = models.TextField(blank=True)
    spare_parts_used = models.TextField(blank=True)
    client_work_order = models.CharField(max_length=60, blank=True)
    is_closed = models.BooleanField(default=False)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        "security.User", on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_by = models.ForeignKey(
        "security.User", on_delete=models.SET_NULL, null=True, related_name="+"
    )
    # What motivated the work, if it came from a report's recommendation.
    recommendation = models.ForeignKey(
        "diagnostics.EquipmentLogEntry", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    # The measurement behind an alignment job, if there was one (V3-17).
    alignment_record = models.ForeignKey(
        "alignment.AlignmentRecord", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["-shift_date", "-id"]

    def __str__(self) -> str:
        return f"{self.asset_group_id} · {self.shift_date}"

    @property
    def duration_minutes(self) -> int | None:
        if self.started_at is None or self.ended_at is None:
            return None
        return int((self.ended_at - self.started_at).total_seconds() // 60)


class WorkRecordResponsible(TenantModel):
    """A system user, or an external's bare name — the RGP names contractors
    who never get an account."""

    work_record = models.ForeignKey(WorkRecord, on_delete=models.CASCADE, related_name="responsibles")
    user = models.ForeignKey(
        "security.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    external_name = models.CharField(max_length=120, blank=True)

    def __str__(self) -> str:
        return self.external_name or (self.user.get_full_name() if self.user else "")
