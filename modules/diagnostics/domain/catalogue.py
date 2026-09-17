"""The failure vocabulary each service is allowed to report.

An analyst who types the problem in prose produces a report nobody can count.
A closed list per technique makes "how many misalignments this quarter" a
query instead of a reading exercise — and the ISO reference beside each entry
is what makes the term mean the same thing to the customer.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FaultDefinition:
    code: str
    name_es: str
    name_en: str
    technique: str
    signature: str = ""
    reference: str = ""


VIBRATION: tuple[FaultDefinition, ...] = (
    FaultDefinition("misalignment_parallel", "Desalineamiento paralelo", "Parallel misalignment",
                    "vibration", "2× radial dominante, fase 180° entre acoples", "ISO 20816-3"),
    FaultDefinition("misalignment_angular", "Desalineamiento angular", "Angular misalignment",
                    "vibration", "1× axial alto, fase 180° a través del acople", "ISO 20816-3"),
    FaultDefinition("unbalance", "Desbalance", "Unbalance",
                    "vibration", "1× radial dominante, fase estable", "ISO 21940-11"),
    FaultDefinition("mechanical_looseness", "Soltura mecánica", "Mechanical looseness",
                    "vibration", "Armónicos 2×, 3×… y suelo elevado", "ISO 20816-3"),
    FaultDefinition("excessive_clearance", "Holgura excesiva", "Excessive clearance",
                    "vibration", "Subarmónicos 0.5× y armónicos múltiples", "ISO 20816-3"),
    FaultDefinition("eccentricity", "Excentricidad", "Eccentricity",
                    "vibration", "1× con fase que no cambia al balancear", "ISO 20816-3"),
    FaultDefinition("soft_foot", "Pata coja", "Soft foot",
                    "vibration", "Deformación al soltar pernos; no debe exceder 0.04 mm",
                    "ISO 20816-3"),
    FaultDefinition("bent_shaft", "Eje doblado", "Bent shaft",
                    "vibration", "1× axial alto con fase opuesta entre extremos", "ISO 20816-3"),
    FaultDefinition("bearing_wear", "Desgaste de rodamientos", "Bearing wear",
                    "vibration", "BPFO/BPFI/BSF en envolvente de aceleración", "ISO 15243"),
    FaultDefinition("gear_defect", "Falla de engranajes", "Gear defect",
                    "vibration", "GMF con bandas laterales a la velocidad de giro", "ISO 13373-3"),
    FaultDefinition("resonance", "Resonancia", "Resonance",
                    "vibration", "Amplificación en una frecuencia natural", "ISO 20816-3"),
    FaultDefinition("rub", "Rozamiento", "Rub",
                    "vibration", "Subarmónicos y espectro truncado", "ISO 20816-3"),
    FaultDefinition("belt_pulley", "Fajas o poleas en mal estado", "Belt or pulley wear",
                    "vibration", "Frecuencia de faja y sus armónicos", "ISO 20816-3"),
    FaultDefinition("cavitation", "Cavitación", "Cavitation",
                    "vibration", "Ruido aleatorio de banda ancha en alta frecuencia",
                    "ISO 20816-3"),
    FaultDefinition("electrical_fault", "Falla eléctrica en motor", "Motor electrical fault",
                    "vibration", "2× frecuencia de línea y bandas de paso de polos",
                    "ISO 20816-3"),
    FaultDefinition("lubrication_deficiency", "Deficiencia de lubricación",
                    "Lubrication deficiency", "vibration",
                    "Envolvente elevada sin frecuencias de defecto", "ISO 15243"),
    FaultDefinition("induced_stress", "Tensiones inducidas", "Induced stress",
                    "vibration", "Cambio de vibración al soltar bridas o tuberías",
                    "ISO 20816-3"),
)

# Two families under one technique, because the plant uses both: ultrasound
# as a condition-monitoring tool (leaks, partial discharge) and as a
# non-destructive test of material (cracks, porosity).
ULTRASOUND: tuple[FaultDefinition, ...] = (
    FaultDefinition("air_leak", "Fuga de aire o gas", "Air or gas leak",
                    "ultrasound", "Ruido de banda ancha en el punto de fuga", "ISO 29821"),
    FaultDefinition("steam_trap", "Trampa de vapor defectuosa", "Failed steam trap",
                    "ultrasound", "Flujo continuo en lugar de ciclado", "ISO 29821"),
    FaultDefinition("partial_discharge", "Descarga parcial", "Partial discharge",
                    "ultrasound", "Corona, tracking o arco en media y alta tensión",
                    "IEC 60270"),
    FaultDefinition("valve_leak", "Paso interno de válvula", "Valve internal leak",
                    "ultrasound", "Ultrasonido aguas abajo con válvula cerrada", "ISO 29821"),
    FaultDefinition("bearing_friction", "Fricción en rodamiento", "Bearing friction",
                    "ultrasound", "Incremento de dB sobre la línea base del punto",
                    "ISO 29821"),
    FaultDefinition("crack", "Fisura", "Crack",
                    "ultrasound", "Eco de discontinuidad plana", "ISO 5817 / ISO 6520-1"),
    FaultDefinition("porosity", "Microporo o porosidad", "Porosity",
                    "ultrasound", "Ecos dispersos de pequeña amplitud", "ISO 6520-1"),
    FaultDefinition("gas_pocket", "Burbujas de aire internas", "Internal gas pocket",
                    "ultrasound", "Discontinuidad esférica en el material", "ISO 6520-1"),
    FaultDefinition("undercut", "Socavación", "Undercut",
                    "ultrasound", "Pérdida de sección en el borde del cordón", "ISO 5817"),
    FaultDefinition("lack_of_fusion", "Falta de fusión", "Lack of fusion",
                    "ultrasound", "Eco plano en la interfaz del cordón", "ISO 6520-1"),
    FaultDefinition("slag_inclusion", "Inclusión de escoria", "Slag inclusion",
                    "ultrasound", "Eco irregular dentro del cordón", "ISO 6520-1"),
    FaultDefinition("wall_thinning", "Adelgazamiento de pared", "Wall thinning",
                    "ultrasound", "Espesor por debajo del mínimo de retiro", "ISO 16809"),
)

THERMOGRAPHY: tuple[FaultDefinition, ...] = (
    FaultDefinition("loose_connection", "Conexión floja o de alta resistencia",
                    "Loose or high-resistance connection", "thermography",
                    "Punto caliente localizado en el borne", "NETA MTS / ISO 18434-1"),
    FaultDefinition("phase_imbalance", "Desbalance de fases", "Phase imbalance",
                    "thermography", "Una fase más caliente con la misma carga",
                    "NETA MTS"),
    FaultDefinition("overload", "Sobrecarga", "Overload",
                    "thermography", "Todo el circuito caliente de forma uniforme",
                    "NETA MTS"),
    FaultDefinition("harmonics", "Distorsión armónica", "Harmonic distortion",
                    "thermography", "Neutro más caliente que las fases", "IEEE 519"),
    FaultDefinition("insulation_failure", "Falla de aislamiento", "Insulation failure",
                    "thermography", "Calentamiento en el cuerpo del aislador",
                    "ISO 18434-1"),
    FaultDefinition("component_overheating", "Componente sobrecalentado",
                    "Component overheating", "thermography",
                    "ΔT sobre un componente similar con igual carga", "NETA MTS"),
    FaultDefinition("cooling_deficiency", "Refrigeración deficiente", "Cooling deficiency",
                    "thermography", "Disipador o ventilación obstruida", "ISO 18434-1"),
    FaultDefinition("flow_blockage", "Obstrucción de flujo", "Flow blockage",
                    "thermography", "Gradiente térmico anómalo en la línea", "ISO 18434-1"),
    FaultDefinition("refractory_loss", "Pérdida de refractario o aislamiento térmico",
                    "Refractory or insulation loss", "thermography",
                    "Punto caliente en la carcasa", "ISO 18434-1"),
    FaultDefinition("abnormal_level", "Nivel anormal en recipiente", "Abnormal vessel level",
                    "thermography", "Línea térmica fuera del nivel esperado",
                    "ISO 18434-1"),
    FaultDefinition("bearing_overheating", "Rodamiento sobrecalentado", "Bearing overheating",
                    "thermography", "ΔT frente al rodamiento gemelo", "ISO 18434-1"),
)

OIL: tuple[FaultDefinition, ...] = (
    FaultDefinition("water_contamination", "Contaminación por agua", "Water contamination",
                    "oil_analysis", "Contenido de agua sobre el límite", "ISO 4406"),
    FaultDefinition("particle_contamination", "Contaminación por partículas",
                    "Particle contamination", "oil_analysis",
                    "Código de limpieza fuera de objetivo", "ISO 4406"),
    FaultDefinition("oxidation", "Oxidación del lubricante", "Lubricant oxidation",
                    "oil_analysis", "TAN creciente y viscosidad alterada", "ISO 14830-1"),
    FaultDefinition("wear_metals", "Metales de desgaste", "Wear metals",
                    "oil_analysis", "Fe, Cu o Si sobre la tendencia", "ISO 14830-1"),
    FaultDefinition("dielectric_loss", "Pérdida de rigidez dieléctrica",
                    "Dielectric strength loss", "oil_analysis",
                    "Rigidez por debajo del mínimo", "IEC 60422"),
)

ALL_FAULTS = VIBRATION + ULTRASOUND + THERMOGRAPHY + OIL


def faults_for(technique: str) -> tuple[FaultDefinition, ...]:
    return tuple(fault for fault in ALL_FAULTS if fault.technique == technique)
