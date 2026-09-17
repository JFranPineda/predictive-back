"""Shipped statuses, technique profiles and standards.

These are seeds, not law: `Configuración global > Estados` and
`Configuración global > Normas` let a company add its own. They are declared in
python rather than YAML because the domain tests assert against them.
"""

from __future__ import annotations

from .entities import (
    MachineClass,
    Mounting,
    Standard,
    Status,
    StatusKind,
    TechniqueStatusProfile,
)

# --- statuses ---------------------------------------------------------------
OPERATIONAL = Status(
    code="operational", name="Operativo", kind=StatusKind.CONDITION, severity=10, color="#16a34a"
)
ALARM = Status(
    code="alarm", name="Alarma", kind=StatusKind.CONDITION, severity=20, color="#f59e0b",
    requires_action=True,
)
SHUTDOWN = Status(
    code="shutdown", name="Parada", kind=StatusKind.CONDITION, severity=30, color="#dc2626",
    requires_action=True, is_terminal=True,
)

# Availability: declared, and none of them is measurable — that is the point.
OFF = Status(
    code="off", name="Apagado", kind=StatusKind.AVAILABILITY, severity=0, color="#94a3b8",
    measurable=False,
)
OUT_OF_SERVICE = Status(
    code="out_of_service", name="Fuera de servicio", kind=StatusKind.AVAILABILITY, severity=0,
    color="#64748b", measurable=False,
)
RETIRED = Status(
    code="retired", name="Retirado", kind=StatusKind.AVAILABILITY, severity=0, color="#475569",
    measurable=False,
)
RUNNING = Status(
    code="running", name="En marcha", kind=StatusKind.AVAILABILITY, severity=0, color="#0ea5e9",
    measurable=True,
)

ALL_STATUSES: tuple[Status, ...] = (
    OPERATIONAL, ALARM, SHUTDOWN, OFF, OUT_OF_SERVICE, RETIRED, RUNNING,
)

# --- profiles per technique -------------------------------------------------
PROFILES: tuple[TechniqueStatusProfile, ...] = (
    TechniqueStatusProfile("vibration", (OFF, OPERATIONAL, ALARM, SHUTDOWN)),
    TechniqueStatusProfile("ultrasound", (OFF, OPERATIONAL, ALARM, SHUTDOWN)),
    TechniqueStatusProfile("thermography", (OPERATIONAL, ALARM, SHUTDOWN, OFF)),
    # Maintenance reports availability plus a single "it works" condition; it
    # measures nothing, so it has no alarm band.
    TechniqueStatusProfile("maintenance", (OFF, RETIRED, OUT_OF_SERVICE, OPERATIONAL)),
    TechniqueStatusProfile("lubrication", (OFF, RETIRED, OUT_OF_SERVICE, OPERATIONAL)),
    TechniqueStatusProfile("alignment", (OFF, OPERATIONAL, ALARM, SHUTDOWN)),
)


# Shipped translations for the seeded catalogue. A company that adds its own
# status fills these from the UI; see core.domain.i18n.
TRANSLATIONS: dict[str, dict[str, str]] = {
    "operational": {"es": "Operativo", "en": "Operational"},
    "alarm": {"es": "Alarma", "en": "Alarm"},
    "shutdown": {"es": "Parada", "en": "Shutdown"},
    "off": {"es": "Apagado", "en": "Off"},
    "out_of_service": {"es": "Fuera de servicio", "en": "Out of service"},
    "retired": {"es": "Retirado", "en": "Retired"},
    "running": {"es": "En marcha", "en": "Running"},
    "not_evaluated": {"es": "Sin evaluar", "en": "Not evaluated"},
}


def profile_for(technique_code: str) -> TechniqueStatusProfile:
    for profile in PROFILES:
        if profile.technique_code == technique_code:
            return profile
    raise KeyError(technique_code)


# --- standards --------------------------------------------------------------
# ISO 10816-3 grades by power *and* by what the machine stands on. The power
# ranges are what let the system classify a machine from its nameplate instead
# of asking somebody to remember which group a 45 kW pump belongs to.
#
# Small machines fall outside 10816-3 (it starts at 15 kW), so the classes of
# ISO 10816-1 cover them — which is the range the field crew works in most:
# motors of 0 to 60 HP.
ISO_10816_3_CLASSES = (
    MachineClass(
        "group_2_rigid", "Grupo 2 · cimentación rígida",
        "15 a 300 kW (20 a 400 HP) sobre base rígida",
        power_min_kw=15, power_max_kw=300, mounting=Mounting.RIGID,
    ),
    MachineClass(
        "group_2_flexible", "Grupo 2 · cimentación flexible",
        "15 a 300 kW (20 a 400 HP) sobre base flexible",
        power_min_kw=15, power_max_kw=300, mounting=Mounting.FLEXIBLE,
    ),
    MachineClass(
        "group_1_rigid", "Grupo 1 · cimentación rígida",
        "300 kW a 50 MW sobre base rígida",
        power_min_kw=300, power_max_kw=50_000, mounting=Mounting.RIGID,
    ),
    MachineClass(
        "group_1_flexible", "Grupo 1 · cimentación flexible",
        "300 kW a 50 MW sobre base flexible",
        power_min_kw=300, power_max_kw=50_000, mounting=Mounting.FLEXIBLE,
    ),
)

ISO_10816_1_CLASSES = (
    MachineClass(
        "class_i", "Clase I", "Hasta 15 kW (20 HP): motores y bombas pequeñas",
        power_min_kw=0, power_max_kw=15,
    ),
    MachineClass(
        "class_ii", "Clase II", "15 a 75 kW (20 a 100 HP) sin cimentación especial",
        power_min_kw=15, power_max_kw=75,
    ),
    MachineClass(
        "class_iii", "Clase III", "Sobre 75 kW (100 HP) en cimentación rígida",
        power_min_kw=75, power_max_kw=50_000, mounting=Mounting.RIGID,
    ),
    MachineClass(
        "class_iv", "Clase IV", "Sobre 75 kW (100 HP) en cimentación flexible",
        power_min_kw=75, power_max_kw=50_000, mounting=Mounting.FLEXIBLE,
    ),
)

STANDARDS: tuple[Standard, ...] = (
    Standard(
        code="iso_10816_3",
        name="ISO 10816-3",
        source="Vibración mecánica. Evaluación en máquinas no rotativas, 15 kW a 50 MW",
        machine_classes=ISO_10816_3_CLASSES,
        techniques=("vibration",),
        is_builtin=True,
    ),
    Standard(
        code="iso_20816_3",
        name="ISO 20816-3",
        source="Sucesora de ISO 10816-3, misma clasificación por grupos",
        machine_classes=ISO_10816_3_CLASSES,
        techniques=("vibration",),
        is_builtin=True,
    ),
    Standard(
        code="iso_10816_1",
        name="ISO 10816-1",
        source="Clases I a IV por potencia; cubre las máquinas pequeñas de 0 a 60 HP",
        machine_classes=ISO_10816_1_CLASSES,
        techniques=("vibration",),
        is_builtin=True,
    ),
    Standard(
        code="iso_10816_7",
        name="ISO 10816-7",
        source="Bombas rotodinámicas, categorías I y II",
        machine_classes=(
            MachineClass("category_i", "Categoría I", "Servicio crítico"),
            MachineClass("category_ii", "Categoría II", "Servicio general"),
        ),
        techniques=("vibration",),
        is_builtin=True,
    ),
    Standard(
        code="iso_18436_2",
        name="ISO 18436-2",
        source="Cualificación del personal de análisis vibracional",
        techniques=("vibration",),
        is_builtin=True,
    ),
    Standard(
        code="technical_associates",
        name="Technical Associates of Charlotte",
        source="Severity chart para bombas y conjuntos rotativos",
        techniques=("vibration",),
        is_builtin=True,
    ),
    Standard(
        code="neta_mts",
        name="NETA MTS",
        source="Criterios ΔT para inspección termográfica eléctrica",
        techniques=("thermography",),
        is_builtin=True,
    ),
    Standard(
        code="iso_18434_1",
        name="ISO 18434-1",
        source="Termografía infrarroja aplicada a maquinaria",
        techniques=("thermography",),
        is_builtin=True,
    ),
    Standard(
        code="iso_29821",
        name="ISO 29821",
        source="Ultrasonido aplicado a monitoreo de condición",
        techniques=("ultrasound",),
        is_builtin=True,
    ),
    Standard(
        code="iso_4406",
        name="ISO 4406",
        source="Código de limpieza para fluidos hidráulicos y lubricantes",
        techniques=("oil_analysis",),
        is_builtin=True,
    ),
    Standard(
        code="iso_14830_1",
        name="ISO 14830-1",
        source="Monitoreo de condición mediante tribología (análisis de aceite)",
        techniques=("oil_analysis",),
        is_builtin=True,
    ),
    Standard(
        code="iec_60422",
        name="IEC 60422",
        source="Aceite mineral aislante en equipos eléctricos",
        techniques=("insulating_oil",),
        is_builtin=True,
    ),
)


# Zone boundaries in mm/s RMS, as the tables publish them: good / acceptable
# (alarm) / unacceptable (shutdown).
ISO_BANDS_BY_CLASS: dict[str, tuple[str, str]] = {
    # ISO 10816-3
    "group_2_rigid": ("2.8", "4.5"),
    "group_2_flexible": ("4.5", "7.1"),
    "group_1_rigid": ("4.5", "7.1"),
    "group_1_flexible": ("7.1", "11.0"),
    # ISO 10816-1
    "class_i": ("1.8", "4.5"),
    "class_ii": ("2.8", "7.1"),
    "class_iii": ("4.5", "11.2"),
    "class_iv": ("7.1", "18.0"),
}

# NETA MTS thermographic criteria for electrical equipment. Two comparisons,
# not one: against a similar component under similar load, and against
# ambient. A panel reading 45 °C means nothing until you know which.
NETA_DELTA_SIMILAR = ("4", "15")
NETA_DELTA_AMBIENT = ("11", "40")


def standard_for(code: str) -> Standard:
    for standard in STANDARDS:
        if standard.code == code:
            return standard
    raise KeyError(code)
