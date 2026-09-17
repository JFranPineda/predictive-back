from __future__ import annotations

from django.db import models

from modules.core.infrastructure.models import TenantModel


class NameplateData(TenantModel):
    """What the manufacturer stamped on the machine.

    Rated power and the foundation it sits on are not decoration: ISO grades a
    45 kW pump and a 400 kW one against different limits, so these two fields
    decide which table the readings are judged against.

    One record per equipment rather than a version history. The design calls
    for versioning (docs/02 §6) and it will be needed the day a motor is
    rewound; today nothing reads a past nameplate, and a table nobody queries
    is a table that drifts.
    """

    MOUNTINGS = [("rigid", "Rígida"), ("flexible", "Flexible")]
    SOURCES = [
        ("nameplate_photo", "Foto de placa"),
        ("datasheet", "Ficha técnica"),
        ("manual", "Manual"),
        ("estimated", "Estimado"),
    ]

    equipment = models.OneToOneField(
        "assets.Equipment", on_delete=models.CASCADE, related_name="nameplate"
    )
    manufacturer = models.CharField(max_length=120, blank=True)
    model = models.CharField(max_length=120, blank=True)
    serial_number = models.CharField(max_length=80, blank=True)
    year = models.PositiveSmallIntegerField(null=True, blank=True)

    rated_power_kw = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Potencia nominal. Decide la clase ISO y con ella los límites",
    )
    rated_rpm = models.PositiveIntegerField(null=True, blank=True)
    rated_voltage_v = models.PositiveIntegerField(null=True, blank=True)
    rated_current_a = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    frame_size = models.CharField(max_length=40, blank=True)
    mounting = models.CharField(
        max_length=10, choices=MOUNTINGS, blank=True,
        help_text="Cimentación rígida o flexible, según ISO 10816-3",
    )

    bearing_de = models.CharField(max_length=40, blank=True, help_text="Rodamiento lado acople")
    bearing_nde = models.CharField(max_length=40, blank=True, help_text="Rodamiento lado libre")
    lubricant = models.CharField(max_length=80, blank=True)
    lubricant_interval_h = models.PositiveIntegerField(null=True, blank=True)

    source = models.CharField(max_length=20, choices=SOURCES, default="nameplate_photo")
    notes = models.TextField(blank=True)

    def __str__(self) -> str:
        return f"Placa de {self.equipment_id}"

    @property
    def rated_power_hp(self) -> float | None:
        """The crew reads horsepower off the plate; the tables are in kW."""
        if self.rated_power_kw is None:
            return None
        return round(float(self.rated_power_kw) / 0.7457, 1)
