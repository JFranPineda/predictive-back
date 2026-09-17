from __future__ import annotations

from django.db import models

from modules.core.infrastructure.models import TenantModel, TranslatableModel


class Status(TenantModel, TranslatableModel):
    """One table for both kinds, because a technique shows them in one list.

    `kind` keeps them apart where it matters: a condition is derived from a
    value, an availability is declared by the technician and explains why there
    is no value. Both are configurable — T12 asks for adding more.
    """

    KINDS = [("condition", "Condición"), ("availability", "Disponibilidad")]

    code = models.SlugField(max_length=30)
    name = models.CharField(max_length=60)
    kind = models.CharField(max_length=20, choices=KINDS, db_index=True)
    severity = models.PositiveSmallIntegerField(default=0, help_text="Higher is worse; orders them")
    color = models.CharField(max_length=9, default="#888888")
    requires_action = models.BooleanField(default=False)
    is_terminal = models.BooleanField(default=False)
    measurable = models.BooleanField(
        default=True, help_text="Availability only: can a reading be taken in this state"
    )
    notify_roles = models.JSONField(default=list, blank=True)

    class Meta:
        unique_together = [("company", "code")]
        ordering = ["kind", "severity"]

    def __str__(self) -> str:
        return self.name


class TechniqueStatusProfile(TenantModel):
    """The status vocabulary of one technique: vibration has no RETIRADO,
    maintenance has no ALARMA."""

    technique = models.OneToOneField(
        "measurements.Technique", on_delete=models.CASCADE, related_name="status_profile"
    )
    statuses = models.ManyToManyField(Status, through="TechniqueStatusOption", related_name="profiles")


class TechniqueStatusOption(models.Model):
    profile = models.ForeignKey(TechniqueStatusProfile, on_delete=models.CASCADE, related_name="options")
    status = models.ForeignKey(Status, on_delete=models.PROTECT, related_name="+")
    order = models.PositiveSmallIntegerField(default=0)
    display_name = models.CharField(
        max_length=60, blank=True, help_text="Overrides the status name for this technique only"
    )

    class Meta:
        unique_together = [("profile", "status")]
        ordering = ["order"]


class ThresholdStandard(TenantModel, TranslatableModel):
    """Configuración global > Normas. Built-in ones ship as fixtures; a company
    adds its own here without touching code."""

    code = models.SlugField(max_length=40)
    name = models.CharField(max_length=160)
    source = models.CharField(max_length=240, blank=True)
    description = models.TextField(blank=True)
    is_builtin = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("company", "code")]

    def __str__(self) -> str:
        return self.name


class MachineClass(TranslatableModel):
    """ISO 10816-3 groups machines I..IV; ISO 10816-7 uses categories. The
    groups belong to the standard, not to the equipment."""

    standard = models.ForeignKey(ThresholdStandard, on_delete=models.CASCADE, related_name="machine_classes")
    code = models.SlugField(max_length=30)
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=240, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        unique_together = [("standard", "code")]
        ordering = ["order"]

    def __str__(self) -> str:
        return f"{self.standard.code}/{self.code}"


class ThresholdSet(TenantModel):
    SCOPES = [
        ("global", "Global"),
        ("equipment_type", "Tipo de equipo"),
        ("asset_group_kind", "Tipo de conjunto"),
        ("equipment", "Equipo"),
        ("point", "Punto"),
    ]

    standard = models.ForeignKey(
        ThresholdStandard, on_delete=models.PROTECT, null=True, blank=True, related_name="sets",
        help_text="Empty means a hand-written criterion, which always competes",
    )
    machine_class = models.ForeignKey(
        MachineClass, on_delete=models.PROTECT, null=True, blank=True, related_name="sets"
    )
    scope = models.CharField(max_length=20, choices=SCOPES, db_index=True)
    scope_ref_id = models.CharField(max_length=40, null=True, blank=True, db_index=True)
    magnitude_code = models.SlugField(max_length=40, db_index=True)
    unit_code = models.CharField(max_length=20)
    # `Gs pico` and `Gs p-p` are different criteria for the same magnitude, so
    # aggregation is part of the key, not a label.
    aggregation = models.CharField(max_length=20, default="rms")
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    rationale = models.TextField(blank=True, help_text="Why this override exists")
    author = models.ForeignKey("security.User", on_delete=models.SET_NULL, null=True, related_name="+")

    class Meta:
        indexes = [models.Index(fields=["company", "magnitude_code", "scope", "scope_ref_id"])]


class ThresholdBand(models.Model):
    threshold_set = models.ForeignKey(ThresholdSet, on_delete=models.CASCADE, related_name="bands")
    status = models.ForeignKey(
        Status, on_delete=models.PROTECT, related_name="+",
        limit_choices_to={"kind": "condition"},
    )
    min_value = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    max_value = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order"]
