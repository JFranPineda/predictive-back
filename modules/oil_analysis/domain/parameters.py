"""What a lubricant sample measures.

Two techniques share this module because they share the workflow — take a
sample, send it to a lab, get numbers back days later — but not the limits:
lubricating oil is judged on wear and contamination, insulating oil on
dielectric strength. The 2014 schedule ran 804 lubricant analyses and 11
insulating ones a year, so both are real.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class OilTechnique(StrEnum):
    LUBRICATING = "oil_analysis"
    INSULATING = "insulating_oil"


@dataclass(frozen=True, slots=True)
class OilParameter:
    code: str
    name_es: str
    name_en: str
    unit: str
    technique: OilTechnique
    higher_is_worse: bool = True


LUBRICATING_PARAMETERS: tuple[OilParameter, ...] = (
    OilParameter("viscosity_40", "Viscosidad a 40 °C", "Viscosity at 40 °C", "cSt",
                 OilTechnique.LUBRICATING, higher_is_worse=False),
    OilParameter("viscosity_100", "Viscosidad a 100 °C", "Viscosity at 100 °C", "cSt",
                 OilTechnique.LUBRICATING, higher_is_worse=False),
    OilParameter("tan", "Número ácido total (TAN)", "Total acid number", "mgKOH/g",
                 OilTechnique.LUBRICATING),
    OilParameter("water_ppm", "Contenido de agua", "Water content", "ppm", OilTechnique.LUBRICATING),
    OilParameter("iso_4406", "Código de limpieza ISO 4406", "ISO 4406 cleanliness code", "code",
                 OilTechnique.LUBRICATING),
    OilParameter("pq_index", "Índice ferroso (PQ)", "Ferrous index (PQ)", "index",
                 OilTechnique.LUBRICATING),
    OilParameter("fe_ppm", "Hierro", "Iron", "ppm", OilTechnique.LUBRICATING),
    OilParameter("cu_ppm", "Cobre", "Copper", "ppm", OilTechnique.LUBRICATING),
    OilParameter("si_ppm", "Silicio", "Silicon", "ppm", OilTechnique.LUBRICATING),
    OilParameter("oxidation", "Oxidación", "Oxidation", "Abs/cm", OilTechnique.LUBRICATING),
)

INSULATING_PARAMETERS: tuple[OilParameter, ...] = (
    OilParameter("dielectric_kv", "Rigidez dieléctrica", "Dielectric strength", "kV",
                 OilTechnique.INSULATING, higher_is_worse=False),
    OilParameter("water_ppm", "Contenido de agua", "Water content", "ppm", OilTechnique.INSULATING),
    OilParameter("acidity", "Índice de acidez", "Acidity index", "mgKOH/g", OilTechnique.INSULATING),
    OilParameter("interfacial_tension", "Tensión interfacial", "Interfacial tension", "mN/m",
                 OilTechnique.INSULATING, higher_is_worse=False),
    OilParameter("dga_h2", "Hidrógeno disuelto (DGA)", "Dissolved hydrogen (DGA)", "ppm",
                 OilTechnique.INSULATING),
)

ALL_PARAMETERS = LUBRICATING_PARAMETERS + INSULATING_PARAMETERS


def parameters_for(technique: OilTechnique) -> tuple[OilParameter, ...]:
    return tuple(p for p in ALL_PARAMETERS if p.technique is technique)


def translations_of(parameter: OilParameter) -> dict[str, str]:
    return {"es": parameter.name_es, "en": parameter.name_en}
