"""The RGP (Relato General de Planta) row model.

The customer's asset master is a 4-level sheet where parent cells are only
written when they change — the classic "visual" spreadsheet. Carrying the last
seen value forward is the whole trick, and it belongs in the domain because
getting it wrong silently reparents equipment.
"""

from __future__ import annotations

from dataclasses import dataclass

from .tag import extract_from_cell, parse, split_area_label

FREQUENCY_MAP = {
    "mensual": "monthly",
    "bimestral": "bimonthly",
    "trimestral": "quarterly",
    "semestral": "semiannual",
    "anual": "annual",
}

# NORMAL/ALARMA/PARADA describe condition; APAGADO/RETIRADO describe availability.
# The source mixes them in one column; they are split on the way in.
CONDITION_MAP = {"normal": "normal", "alarma": "alarm", "parada": "shutdown", "alerta": "alert"}
AVAILABILITY_MAP = {
    "apagado": "off",
    "retirado": "retired",
    "equipo retirado": "retired",
    "equipo fuera de servicio": "out_of_service",
    "fuera de servicio": "out_of_service",
}


@dataclass(frozen=True, slots=True)
class RgpRow:
    area_code: str
    area_name: str
    sector: str
    group: str
    equipment_name: str
    client_tag: str | None
    equipment_type: str | None
    frequency: str | None
    condition_status: str | None
    availability_status: str | None
    conclusion: str
    recommendation: str
    source_row: int


def normalise_status(raw: str) -> tuple[str | None, str | None]:
    key = " ".join((raw or "").split()).lower()
    return CONDITION_MAP.get(key), AVAILABILITY_MAP.get(key)


def build_row(cells: dict[str, str], carried: dict[str, str], source_row: int) -> RgpRow:
    """`carried` holds the last non-empty value of each merged parent column."""
    area_raw = cells.get("area") or carried.get("area", "")
    area_code, area_name = split_area_label(area_raw)
    tag = extract_from_cell(cells["equipment"])
    condition, availability = normalise_status(cells.get("status", ""))
    return RgpRow(
        area_code=area_code,
        area_name=area_name,
        sector=" ".join((cells.get("sector") or carried.get("sector", "")).split()),
        group=" ".join((cells.get("group") or carried.get("group", "")).split()),
        equipment_name=" ".join(cells["equipment"].split()).split("TAG")[0].strip(" -"),
        client_tag=tag,
        equipment_type=parse(tag).guessed_type if tag else None,
        frequency=FREQUENCY_MAP.get((cells.get("frequency") or "").strip().lower()),
        condition_status=condition,
        availability_status=availability,
        conclusion=(cells.get("conclusion") or "").strip(),
        recommendation=(cells.get("recommendation") or "").strip(),
        source_row=source_row,
    )
