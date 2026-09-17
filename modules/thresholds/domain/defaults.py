"""Shipped statuses, technique profiles and standards.

These are seeds, not law: `Configuración global > Estados` and
`Configuración global > Normas` let a company add its own. They are declared in
python rather than YAML because the domain tests assert against them.
"""

from __future__ import annotations

from .entities import MachineClass, Standard, Status, StatusKind, TechniqueStatusProfile

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
ISO_10816_3_CLASSES = (
    MachineClass("class_i", "Clase I", "Máquinas pequeñas hasta 15 kW"),
    MachineClass("class_ii", "Clase II", "Máquinas medianas de 15 a 75 kW"),
    MachineClass("class_iii", "Clase III", "Máquinas grandes sobre cimentación rígida"),
    MachineClass("class_iv", "Clase IV", "Máquinas grandes sobre cimentación flexible"),
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


def standard_for(code: str) -> Standard:
    for standard in STANDARDS:
        if standard.code == code:
            return standard
    raise KeyError(code)
