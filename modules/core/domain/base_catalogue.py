"""What every customer database starts from (v4 Phase 6, decision P0-b).

Units, techniques, magnitudes, operating parameters and roles: what the
modules need to install and a plant needs to start recording, with no books
and no demo. Nothing here names a customer, an instrument or a supplier, and
it sets no limits (decision P6-e): those are data, loaded on purpose.

Laid down by `manage.py catalog base`; `import_ipsa` and `seed_demo` start
from the same catalogue.
"""

from __future__ import annotations

UNITS = [
    ("mm/s", "Milímetros por segundo", {"es": "Milímetros por segundo", "en": "Millimetres per second"}),
    ("gE", "Envolvente de aceleración", {"es": "Envolvente de aceleración", "en": "Acceleration envelope"}),
    ("g", "Aceleración", {"es": "Aceleración", "en": "Acceleration"}),
    ("°C", "Grados Celsius", {"es": "Grados Celsius", "en": "Degrees Celsius"}),
    ("dB", "Decibelios", {"es": "Decibelios", "en": "Decibels"}),
    ("PSI", "Libras por pulgada cuadrada",
     {"es": "Libras por pulgada cuadrada", "en": "Pounds per square inch"}),
    ("Hz", "Hercios", {"es": "Hercios", "en": "Hertz"}),
    ("rpm", "Revoluciones por minuto", {"es": "Revoluciones por minuto", "en": "Revolutions per minute"}),
    ("cSt", "Centistokes", {"es": "Centistokes", "en": "Centistokes"}),
    ("ppm", "Partes por millón", {"es": "Partes por millón", "en": "Parts per million"}),
    ("kV", "Kilovoltios", {"es": "Kilovoltios", "en": "Kilovolts"}),
    ("mgKOH/g", "Número ácido", {"es": "Miligramos de KOH por gramo", "en": "Milligrams KOH per gram"}),
    # Wall thickness, and what the rollers module's install hook looks up.
    ("mm", "Milímetros", {"es": "Milímetros", "en": "Millimetres"}),
]

TECHNIQUES = [
    # code, es, en, module
    ("vibration", "Análisis de vibraciones", "Vibration analysis", "vibration"),
    ("ultrasound", "Análisis de ultrasonido", "Ultrasound analysis", "ultrasound"),
    ("thermography", "Termografía", "Thermography", "thermography"),
    ("oil_analysis", "Análisis de aceite", "Oil analysis", "oil_analysis"),
    ("insulating_oil", "Aceite dieléctrico", "Insulating oil", "oil_analysis"),
    ("maintenance", "Mantenimiento", "Maintenance", "operating_data"),
    ("lubrication", "Lubricación", "Lubrication", "operating_data"),
    ("alignment", "Alineamiento", "Alignment", "alignment"),
    ("topography", "Topografía", "Topography", "topography"),
    ("ndt_penetrant", "Tintes penetrantes", "Dye penetrant testing", "measurements"),
    ("ndt_magnetic", "Partículas magnéticas", "Magnetic particle testing", "measurements"),
    ("ndt_thickness", "END · Espesores UT", "NDT · UT thickness", "ultrasound"),
]

# No reading plan seeds a topography visit's plan for it (V3-18): the
# close-time check is what makes it mandatory.
PLAN_REQUIRED = ("topography",)
# No magnitude, no reading plan: a photo and a conclusion close the visit (V3-20).
EVIDENCE_ONLY = ("ndt_penetrant", "ndt_magnetic")

MAGNITUDES = [
    # code, technique, es, en, unit, aggregation, decimals
    ("vel_rms", "vibration", "Velocidad vibracional", "Vibration velocity", "mm/s", "rms", 2),
    ("env_accel", "vibration", "Envolvente de aceleración", "Acceleration envelope", "gE", "peak", 2),
    ("temp", "thermography", "Temperatura", "Temperature", "°C", "max", 0),
    ("delta_temp", "thermography", "ΔT contra componente similar",
     "ΔT against a similar component", "°C", "max", 1),
    ("delta_temp_ambient", "thermography", "ΔT sobre ambiente", "ΔT over ambient",
     "°C", "max", 1),
    ("us_db", "ultrasound", "Nivel de ultrasonido", "Ultrasound level", "dB", "avg", 1),
    ("viscosity_40", "oil_analysis", "Viscosidad a 40 °C", "Viscosity at 40 °C", "cSt", "avg", 1),
    ("water_ppm", "oil_analysis", "Contenido de agua", "Water content", "ppm", "avg", 0),
    ("dielectric_kv", "insulating_oil", "Rigidez dieléctrica", "Dielectric strength", "kV", "avg", 1),
    ("thickness_mm", "ndt_thickness", "Espesor de pared", "Wall thickness", "mm", "min", 2),
]

# What differs from a magnitude's defaults (higher is worse, one value per axis).
MAGNITUDE_OPTIONS = {
    "thickness_mm": {"higher_is_worse": False, "per_axis": False},
}

# The magnitude each technique's traffic light reads first.
HEADLINES = {
    "vibration": "vel_rms",
    "thermography": "delta_temp",
    "ultrasound": "us_db",
    "oil_analysis": "viscosity_40",
    "insulating_oil": "dielectric_kv",
    "ndt_thickness": "thickness_mm",
}

OPERATING_PARAMETERS = [
    # code, es, en, unit, technique ("" = any), applies_to, cumulative
    ("rpm", "Velocidad", "Speed", "rpm", "", [], False),
    ("freq_hz", "Frecuencia", "Frequency", "Hz", "", [], False),
    ("current_a", "Amperaje", "Current", "A", "", ["motor"], False),
    ("voltage_v", "Voltaje", "Voltage", "V", "", ["motor"], False),
    ("power_kw", "Potencia", "Power", "kW", "", ["motor"], False),
    ("power_factor", "Factor de potencia", "Power factor", "", "", ["motor"], False),
    ("running_hours", "Horas acumuladas", "Running hours", "h", "", [], True),
    ("suction_psi", "Presión de succión", "Suction pressure", "PSI", "", ["pump"], False),
    ("discharge_psi", "Presión de descarga", "Discharge pressure", "PSI", "", ["pump"], False),
    ("flushing_coupling_psi", "Presión flushing lado acople", "Flushing pressure, coupling end",
     "PSI", "", ["pump"], False),
    ("flushing_free_psi", "Presión flushing lado libre", "Flushing pressure, free end",
     "PSI", "", ["pump"], False),
    ("ambient_temp", "Temperatura ambiente", "Ambient temperature", "°C", "thermography", [], False),
    ("emissivity", "Emisividad", "Emissivity", "", "thermography", [], False),
    ("load_pct", "Carga", "Load", "%", "thermography", [], False),
    ("oil_hours", "Horas del lubricante", "Oil hours", "h", "oil_analysis", [], True),
]

ROLES = {
    "company_admin": ["*"],
    "engineer": [
        "assets.view_equipment", "assets.manage_equipment", "assets.manage_point",
        "measurements.view_reading", "measurements.add_reading", "measurements.edit_reading",
        "thresholds.view_set", "thresholds.manage_set", "thresholds.manage_status",
        "thresholds.manage_standard", "services.view", "services.view_authorship",
        "services.close_visit", "services.manage_order", "diagnostics.view",
        "diagnostics.add_entry", "diagnostics.close_recommendation", "reports.view",
        "reports.create", "reports.issue", "summaries.view", "summaries.export",
        "media.view", "media.upload", "blueprints.view", "nameplate.view",
        "core.manage_modules", "security.view_user", "licensing.view_status",
    ],
    "technician": [
        "assets.view_equipment", "measurements.view_reading", "measurements.add_reading",
        "services.view", "services.view_authorship", "media.view", "media.upload",
        "diagnostics.view", "diagnostics.add_entry", "summaries.view",
        "blueprints.view", "nameplate.view", "thresholds.view_set",
    ],
    "external_inspector": [
        "assets.view_equipment", "blueprints.view", "nameplate.view",
        "measurements.view_reading", "measurements.add_reading",
        "services.view", "services.view_authorship",
        "media.view", "media.upload", "diagnostics.view", "diagnostics.add_entry",
        "summaries.view",
    ],
    "client_viewer": [
        "assets.view_equipment", "measurements.view_reading", "summaries.view",
        "reports.view", "services.view",
    ],
}
