from __future__ import annotations

from django.db import models

from modules.core.infrastructure.models import TenantModel

MONITORING_FREQUENCIES = [
    ("monthly", "Mensual"),
    ("bimonthly", "Bimestral"),
    ("quarterly", "Trimestral"),
    ("semiannual", "Semestral"),
    ("annual", "Anual"),
    ("on_demand", "Bajo demanda"),
]

FREQUENCY_DAYS = {
    "monthly": 30, "bimonthly": 60, "quarterly": 90,
    "semiannual": 180, "annual": 365, "on_demand": 0,
}


class Plant(TenantModel):
    code = models.SlugField(max_length=40)
    name = models.CharField(max_length=160)
    timezone = models.CharField(max_length=64, default="America/Lima")
    address = models.CharField(max_length=240, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("company", "code")]


class Area(TenantModel):
    """Source sheets write area as "501 - PACKAGING CERVEZA": code and name in
    one string. They are split here; `parent` covers the real cases where one
    area is a subdivision of another (121/122 AIRE COMPRIMIDO, 561S/562S...)."""

    plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name="areas")
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="children"
    )
    code = models.CharField(max_length=20, db_index=True)
    name = models.CharField(max_length=160)
    criticality = models.PositiveSmallIntegerField(default=3, help_text="1 highest")
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("plant", "code")]
        ordering = ["code"]


class Sector(TenantModel):
    area = models.ForeignKey(Area, on_delete=models.CASCADE, related_name="sectors")
    code = models.SlugField(max_length=40, blank=True)
    name = models.CharField(max_length=160)

    class Meta:
        ordering = ["name"]


class AssetGroup(TenantModel):
    """The rotating set (motor+pump, motor+compressor...). This is what gets
    aligned, what gets one report, and what the point numbering belongs to."""

    KINDS = [
        ("motor_pump", "Motor-Bomba"),
        ("motor_compressor", "Motor-Compresor"),
        ("motor_gearbox", "Motor-Reductor"),
        ("motor_fan", "Motor-Ventilador"),
        ("motor_blower", "Motor-Soplador"),
        ("standalone", "Equipo aislado"),
    ]

    sector = models.ForeignKey(Sector, on_delete=models.CASCADE, related_name="groups")
    code = models.SlugField(max_length=60)
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=30, choices=KINDS, default="standalone")
    criticality = models.PositiveSmallIntegerField(default=3)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("company", "code")]


class Equipment(TenantModel):
    TYPES = [
        ("motor", "Motor"), ("pump", "Bomba"), ("compressor", "Compresor"),
        ("gearbox", "Reductor"), ("fan", "Ventilador"), ("blower", "Soplador"),
        ("bearing_housing", "Chumacera"), ("other", "Otro"),
    ]
    POSITIONS = [
        ("driver", "Motriz"), ("driven", "Conducido"), ("intermediate", "Intermedio"),
    ]

    asset_group = models.ForeignKey(AssetGroup, on_delete=models.CASCADE, related_name="equipments")
    # Mandatory and unique: every reading, photo, report and audit row points
    # at it. Auto-generated from the client TAG when free, so nobody types it.
    asset_code = models.SlugField(max_length=60, help_text="Internal key. Always unique")
    client_tag = models.CharField(
        max_length=60, db_index=True, blank=True,
        help_text="Customer TAG. Optional and NOT unique: sources repeat it across motor and pump",
    )
    name = models.CharField(max_length=200)
    equipment_type = models.CharField(max_length=30, choices=TYPES)
    position_in_group = models.CharField(max_length=20, choices=POSITIONS, default="driven")
    # Which standard judges this equipment, and under which of its classes.
    # Changing the standard changes the limits and therefore the status,
    # without touching a single threshold row.
    applied_standard = models.ForeignKey(
        "thresholds.ThresholdStandard", on_delete=models.PROTECT, null=True, blank=True,
        related_name="equipments",
    )
    machine_class = models.ForeignKey(
        "thresholds.MachineClass", on_delete=models.PROTECT, null=True, blank=True,
        related_name="equipments",
    )
    monitoring_frequency = models.CharField(
        max_length=20, choices=MONITORING_FREQUENCIES, default="monthly"
    )
    availability_status = models.ForeignKey(
        "thresholds.Status", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        limit_choices_to={"kind": "availability"},
    )
    condition_status = models.ForeignKey(
        "thresholds.Status", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        limit_choices_to={"kind": "condition"},
        help_text="Derived from the last evaluated reading",
    )
    condition_updated_at = models.DateTimeField(null=True, blank=True)
    installed_at = models.DateField(null=True, blank=True)
    retired_at = models.DateField(null=True, blank=True)

    class Meta:
        unique_together = [("company", "asset_code")]
        indexes = [models.Index(fields=["company", "client_tag"])]

    def save(self, *args, **kwargs):
        if not self.asset_code:
            from modules.assets.domain.asset_code import generate

            self.asset_code = generate(
                area_code=self.asset_group.sector.area.code,
                equipment_type=self.equipment_type,
                client_tag=self.client_tag or None,
                taken=Equipment.objects.for_company(self.company_id).values_list(
                    "asset_code", flat=True
                ),
            )
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} [{self.client_tag or self.asset_code}]"


class MeasurementPoint(TenantModel):
    """Numbering is positional inside the AssetGroup, as in the source sheets:
    1 = motor free end, 2 = motor coupling end, 3 = pump coupling end,
    4 = pump opposite coupling."""

    SIDES = [
        ("free_end", "Lado libre"), ("coupling_end", "Lado acople"),
        ("opposite_coupling", "Lado opuesto a acople"), ("inboard", "Interior"),
        ("outboard", "Exterior"), ("custom", "Otro"),
    ]
    AXES = [("H", "Horizontal"), ("V", "Vertical"), ("A", "Axial"), ("N", "Sin eje")]
    TYPES = [
        ("bearing", "Rodamiento"), ("electrical", "Eléctrico"), ("thermal", "Térmico"),
        ("ultrasound", "Ultrasonido"), ("lubrication", "Lubricación"), ("process", "Proceso"),
    ]

    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name="points")
    number = models.PositiveSmallIntegerField()
    side = models.CharField(max_length=20, choices=SIDES, default="custom")
    axis = models.CharField(max_length=1, choices=AXES, default="N")
    point_type = models.CharField(max_length=20, choices=TYPES, default="bearing")
    label = models.CharField(max_length=20, blank=True, help_text='Derived: "1H", "3V"')
    # Normalised 0..1 so the blueprint can be replaced at another resolution
    # without relocating every point.
    blueprint_x = models.FloatField(null=True, blank=True)
    blueprint_y = models.FloatField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("equipment", "number", "axis")]
        ordering = ["number", "axis"]

    def save(self, *args, **kwargs):
        if not self.label:
            self.label = f"{self.number}{self.axis if self.axis != 'N' else ''}"
        super().save(*args, **kwargs)
