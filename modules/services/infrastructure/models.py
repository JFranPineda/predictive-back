from __future__ import annotations

from django.db import models

from modules.core.infrastructure.models import TenantModel

FREQUENCY_DAYS = [(30, "30 días"), (60, "60 días"), (90, "90 días"),
                  (120, "120 días"), (150, "150 días"), (180, "180 días"), (365, "365 días")]


class ServicePlan(TenantModel):
    plant = models.ForeignKey("assets.Plant", on_delete=models.CASCADE, related_name="plans")
    year = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=120)
    status = models.CharField(max_length=20, default="draft")

    class Meta:
        unique_together = [("plant", "year", "name")]


class PlanLine(TenantModel):
    plan = models.ForeignKey(ServicePlan, on_delete=models.CASCADE, related_name="lines")
    technique = models.ForeignKey("measurements.Technique", on_delete=models.PROTECT, related_name="+")
    frequency_days = models.PositiveSmallIntegerField(choices=FREQUENCY_DAYS, default=30)
    scope = models.CharField(max_length=20, default="area")
    scope_ref_id = models.CharField(max_length=40, blank=True)
    planned_points = models.PositiveIntegerField(default=0)
    planned_mandays = models.DecimalField(max_digits=6, decimal_places=1, default=0)


class ServiceOrder(TenantModel):
    STATUSES = [("planned", "Programada"), ("in_progress", "En ejecución"),
                ("done", "Ejecutada"), ("cancelled", "Anulada")]

    plant = models.ForeignKey("assets.Plant", on_delete=models.PROTECT, related_name="orders")
    technique = models.ForeignKey("measurements.Technique", on_delete=models.PROTECT, related_name="+")
    code = models.CharField(max_length=40, help_text="MPd-AV-N°006-13")
    client_work_order = models.CharField(
        max_length=40, blank=True, help_text="OT del ERP del cliente (JD Edwards, SAP...)"
    )
    # Written down, not integrated. When the customer's ERP is wired in, the ids
    # it returns land here without a migration.
    external_refs = models.JSONField(default=dict, blank=True)
    scheduled_from = models.DateField()
    scheduled_to = models.DateField()
    status = models.CharField(max_length=20, choices=STATUSES, default="planned")
    lead_analyst = models.ForeignKey("security.User", on_delete=models.SET_NULL, null=True, related_name="+")
    supervisor = models.ForeignKey("security.User", on_delete=models.SET_NULL, null=True, related_name="+")

    class Meta:
        unique_together = [("company", "code")]


class ServiceVisit(TenantModel):
    """The hinge: every reading, photo, operating value and log entry hangs off
    a visit, which is what makes "what was done on 2013-12-17" answerable."""

    service_order = models.ForeignKey(ServiceOrder, on_delete=models.CASCADE, related_name="visits")
    equipment = models.ForeignKey("assets.Equipment", on_delete=models.PROTECT, related_name="visits")
    visited_at = models.DateTimeField(db_index=True)
    availability_status = models.ForeignKey(
        "thresholds.Status", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text="Declared by the technician, from the technique's profile",
    )
    instrument = models.ForeignKey(
        "measurements.Instrument", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    duration_min = models.PositiveSmallIntegerField(null=True, blank=True)
    geo = models.JSONField(null=True, blank=True)
    is_closed = models.BooleanField(default=False)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey("security.User", on_delete=models.SET_NULL, null=True, related_name="+")

    class Meta:
        indexes = [models.Index(fields=["company", "equipment", "-visited_at"])]


class VisitParticipant(models.Model):
    """"Quién o quiénes": several people can work one visit, and each of them
    may edit it while it is open."""

    ROLES = [("lead_analyst", "Inspector analista"), ("assistant", "Asistente"),
             ("supervisor", "Supervisor"), ("client_witness", "Testigo del cliente")]

    visit = models.ForeignKey(ServiceVisit, on_delete=models.CASCADE, related_name="participants")
    user = models.ForeignKey("security.User", on_delete=models.PROTECT, related_name="visit_participations")
    role = models.CharField(max_length=20, choices=ROLES, default="lead_analyst")
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("visit", "user")]
