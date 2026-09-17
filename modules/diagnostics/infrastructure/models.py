from __future__ import annotations

from django.db import models

from modules.core.infrastructure.models import TenantModel, TranslatableModel


class FaultMode(TenantModel, TranslatableModel):
    """The vocabulary the reports already use: desalineamiento, soltura
    mecánica, desgaste de rodamientos, pata coja, GMF, tensiones inducidas…"""

    code = models.SlugField(max_length=40)
    name = models.CharField(max_length=120)
    technique_code = models.SlugField(max_length=30, blank=True, db_index=True)
    typical_signature = models.CharField(max_length=240, blank=True)
    iso_reference = models.CharField(max_length=80, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("company", "code")]
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class EquipmentLogEntry(TenantModel):
    """A dated line of the equipment's diary.

    The source reports keep antecedentes, conclusiones and recomendaciones as
    dated lines, not as one free-text field — that is how a 2013 background can
    sit next to a 2014 conclusion in the same document. Each line keeps its own
    author, so the supervisor's recommendation is never attributed to the
    inspector.
    """

    TYPES = [
        ("background", "Antecedente"),
        ("observation", "Observación"),
        ("failure_mode", "Modo de falla"),
        ("finding", "Hallazgo"),
        ("conclusion", "Conclusión"),
        ("recommendation", "Recomendación"),
        ("action_taken", "Acción realizada"),
        ("note", "Nota"),
    ]
    STATUSES = [
        ("open", "Abierta"), ("scheduled", "Programada"),
        ("done", "Ejecutada"), ("dismissed", "Descartada"),
    ]

    equipment = models.ForeignKey(
        "assets.Equipment", on_delete=models.CASCADE, related_name="log_entries"
    )
    service_visit = models.ForeignKey(
        "services.ServiceVisit", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="log_entries",
    )
    entry_type = models.CharField(max_length=20, choices=TYPES, db_index=True)
    entry_date = models.DateField(db_index=True)
    text = models.TextField()
    author = models.ForeignKey("security.User", on_delete=models.SET_NULL, null=True, related_name="+")
    fault_modes = models.ManyToManyField(FaultMode, blank=True, related_name="entries")
    severity = models.PositiveSmallIntegerField(default=3, help_text="1 highest")
    # Recommendations are followed up; in the spreadsheets they were written
    # and then lost.
    status = models.CharField(max_length=20, choices=STATUSES, blank=True)
    due_date = models.DateField(null=True, blank=True)
    tolerance_note = models.CharField(
        max_length=200, blank=True, help_text='e.g. "la pata coja no debe exceder 0.04 mm"'
    )

    class Meta:
        ordering = ["-entry_date", "entry_type"]
        indexes = [models.Index(fields=["company", "equipment", "-entry_date"])]
