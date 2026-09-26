"""What each report says, assembled from the same data the screens read.

Every builder returns plain dicts for one template; the HTML preview, the PDF
and the workbook are three renderings of the same context, so they can never
disagree about a value.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date

from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from modules.reports.domain.pareto import LABELS, STATES, pareto, state_for
from modules.reports.domain.trend_svg import PALETTE, trend_svg
from modules.reports.infrastructure.images import embedded, logo

MAX_COLUMNS = 12
MAX_SERIES = 8
MAX_PHOTOS = 12
PAST_TYPES = ("background", "conclusion")
PRESENT_TYPES = ("observation", "finding", "failure_mode", "conclusion")


class _MatrixRequest:
    """`build_matrix` reads a request; the report asks it for one service."""

    def __init__(self, request, technique: str) -> None:
        self.company_id = request.company_id
        self.user = request.user
        self.language = getattr(request, "language", "es")
        self.query_params = {"technique": technique}


def _company(request) -> str:
    from modules.core.models import Company

    return Company.objects.filter(id=request.company_id).values_list("name", flat=True).first() or ""


def _day(value) -> str:
    return timezone.localtime(value).strftime("%d/%m/%Y") if hasattr(value, "tzinfo") else value.strftime(
        "%d/%m/%Y"
    )


def _span(first, last) -> str:
    """One day, or a range with an en dash as the customer's reports print it."""
    return _day(first) if first == last else f"{_day(first)} \u2013 {_day(last)}"


def _trim(value: str | None, decimals: int) -> str:
    if value in (None, ""):
        return ""
    try:
        return f"{float(value):.{decimals}f}"
    except ValueError:
        return str(value)


def _entry(row) -> dict:
    return {
        "date": row.entry_date.strftime("%d/%m/%Y"),
        "type": row.get_entry_type_display(),
        "text": row.text,
        "author": row.author.get_full_name() if row.author else "",
        "status": row.get_status_display() if row.status else "",
    }


def _plain(value) -> str:
    """4.5000 → 4.5: the column keeps four decimals, a printed limit does not."""
    return "—" if value is None else format(value.normalize(), "f")


def _worst(statuses):
    present = [status for status in statuses if status is not None]
    return max(present, key=lambda status: status.severity) if present else None


# --------------------------------------------------------------------------
# Informe MPd — one train, one order (V3-23 AC-01)
# --------------------------------------------------------------------------


def build_mpd(request, order_id: int, group_id: int) -> dict:
    from modules.assets.models import AssetGroup
    from modules.diagnostics.models import EquipmentLogEntry
    from modules.measurements.interfaces.matrix_views import build_matrix
    from modules.measurements.models import Reading, Spectrum
    from modules.media.infrastructure.models import MediaAsset
    from modules.services.models import ServiceOrder, ServiceVisit

    order = (
        ServiceOrder.objects.for_company(request.company_id)
        .select_related("technique", "plant", "provider", "lead_analyst")
        .filter(id=order_id)
        .first()
    )
    group = (
        AssetGroup.objects.for_company(request.company_id)
        .select_related("sector__area")
        .filter(id=group_id)
        .first()
    )
    if order is None or group is None:
        raise NotFound("Esa orden o ese conjunto no existen")
    visits = list(
        ServiceVisit.objects.for_company(request.company_id)
        .filter(service_order=order, equipment__asset_group=group)
        .select_related("equipment", "instrument", "availability_status")
        .prefetch_related("participants__user", "fault_modes")
        .order_by("visited_at", "id")
    )
    if not visits:
        raise ValidationError("Esa orden no tiene visitas en ese conjunto")
    language = getattr(request, "language", "es")
    equipments = list(group.equipments.order_by("order_in_group", "id"))
    first_day, last_day = visits[0].visited_at.date(), visits[-1].visited_at.date()

    readings = list(
        Reading.objects.for_company(request.company_id)
        .filter(service_visit__in=visits)
        .select_related("condition_status", "point", "image", "magnitude")
    )
    state = _worst(r.condition_status for r in readings)
    people, roles = [], {"lead_analyst": "Analista", "assistant": "Inspector", "supervisor": "Supervisor"}
    for visit in visits:
        for participant in visit.participants.all():
            name = f"{participant.user.get_full_name()} ({roles.get(participant.role, participant.role)})"
            if name not in people:
                people.append(name)

    entries = EquipmentLogEntry.objects.for_company(request.company_id).select_related("author")
    past = entries.filter(
        equipment__in=equipments, entry_type__in=PAST_TYPES, entry_date__lt=first_day
    ).order_by("-entry_date")[:10]
    present = entries.filter(service_visit__in=visits, entry_type__in=PRESENT_TYPES).order_by(
        "entry_date", "id"
    )
    recommendations = entries.filter(equipment__in=equipments, entry_type="recommendation").filter(
        service_visit__in=visits
    ) | entries.filter(
        equipment__in=equipments, entry_type="recommendation", status__in=("open", "scheduled"),
        entry_date__lte=last_day,
    )
    faults = []
    for visit in visits:
        faults.extend(fault.translated("name", language) for fault in visit.fault_modes.all())
        if visit.other_fault:
            faults.append(f"Otros: {visit.other_fault}")

    matrix = build_matrix(_MatrixRequest(request, order.technique.code), equipments[0], "group")
    columns = [(i, c) for i, c in enumerate(matrix["columns"]) if c["date"] <= last_day.isoformat()]
    columns = columns[-MAX_COLUMNS:]
    blocks = []
    for block in matrix["blocks"]:
        rows = [
            {
                "component": row["component"],
                "label": row["label"],
                "values": [
                    _trim((row["cells"][i] or {}).get("value"), block["decimals"]) for i, _ in columns
                ],
                "colors": [(row["cells"][i] or {}).get("status_color") or "" for i, _ in columns],
            }
            for row in block["rows"]
        ]
        for row in rows:
            row["cells"] = [
                {"value": value, "color": color}
                for value, color in zip(row["values"], row["colors"], strict=True)
            ]
        drawn = rows[:MAX_SERIES]
        series = [
            (row["label"], [None if value == "" else float(value) for value in row["values"]])
            for row in drawn
        ]
        blocks.append({
            "title": block["title"],
            "unit": block["unit"],
            "aggregation": block["aggregation"],
            "rows": rows,
            "trend": trend_svg(
                [_short(c["date"]) for _, c in columns], series, unit=block["unit"], end_labels=False
            ),
            # The same point number repeats across machines ("3H" of the
            # gearbox and of the pump), so the legend names the machine too.
            "legend": [
                {"color": PALETTE[index % len(PALETTE)], "label": f"{row['component']} · {row['label']}"}
                for index, row in enumerate(drawn)
            ],
            "limits": _limits(request, equipments, block["magnitude_code"], block["aggregation"]),
        })

    photos = MediaAsset.objects.for_company(request.company_id)
    own = photos.filter(owner_type="group", owner_id=group.id).order_by("-created_at")
    schematic = own.filter(kind="schematic").first()
    site = own.filter(kind="site_photo").first()
    spectra = [
        {"src": embedded(row.image), "caption": f"{row.point.label} · {row.get_spectrum_type_display()}"}
        for row in Spectrum.objects.for_company(request.company_id)
        .filter(service_visit__in=visits, image__isnull=False)
        .select_related("image", "point")[:MAX_PHOTOS]
    ]
    seen, thermograms = set(), []
    for reading in readings:
        if reading.image_id and reading.image_id not in seen:
            seen.add(reading.image_id)
            thermograms.append({"src": embedded(reading.image), "caption": reading.point.label})
    evidence = [
        {"src": embedded(asset), "caption": asset.caption}
        for asset in photos.filter(owner_type="visit", owner_id__in=[v.id for v in visits], kind="photo")[
            :MAX_PHOTOS
        ]
    ]

    return {
        "logo": logo(),
        "title": "Informe de mantenimiento predictivo",
        "header": {
            "client": _company(request),
            "plant": order.plant.name,
            "area": f"{group.sector.area.code} - {group.sector.area.name}",
            "sector": group.sector.name,
            "group": group.name,
            "equipments": ", ".join(f"{e.name} ({e.client_tag or e.asset_code})" for e in equipments),
            "order": order.code,
            "client_order": order.client_work_order,
            "technique": order.technique.translated("name", language),
            "provider": order.provider.name if order.provider else "",
            "dates": _span(first_day, last_day),
            "people": ", ".join(people),
            "analyst": order.lead_analyst.get_full_name() if order.lead_analyst else "",
            "instruments": ", ".join(sorted({v.instrument.name for v in visits if v.instrument})),
            "state": None if state is None else {
                "name": state.translated("name", language), "color": state.color,
            },
        },
        "background": [_entry(row) for row in reversed(list(past))],
        "present": [_entry(row) for row in present],
        "faults": faults,
        "recommendations": [_entry(row) for row in recommendations.distinct().order_by("entry_date", "id")],
        "dates": [_short(c["date"]) for _, c in columns],
        "blocks": blocks,
        "schematic": embedded(schematic),
        "site_photo": embedded(site),
        "spectra": [row for row in spectra if row["src"]],
        "thermograms": [row for row in thermograms if row["src"]],
        "evidence": [row for row in evidence if row["src"]],
        "alignment": _alignment(request, visits),
        "filename": f"informe-mpd-{order.code}-{group.name}"[:120],
    }


def _short(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d/%m/%y")


def _limits(request, equipments, magnitude_code: str, aggregation: str) -> list[dict]:
    """The criteria in force for this magnitude, resolved through the same
    cascade that graded the readings, once per machine of the train."""
    from modules.thresholds.application.evaluation import context_for
    from modules.thresholds.domain.services import resolve
    from modules.thresholds.infrastructure.repositories import DjangoThresholdRepository
    from modules.thresholds.models import ThresholdStandard

    repository = DjangoThresholdRepository(getattr(request, "language", "es"))
    candidates = repository.candidates(request.company_id, magnitude_code)
    standards = dict(
        ThresholdStandard.objects.for_company(request.company_id).values_list("code", "name")
    )
    found: dict[int, dict] = {}
    for machine in equipments:
        try:
            context = context_for(machine, magnitude_code, aggregation)
        except ValueError:
            continue
        chosen = resolve(candidates, context, date.today())
        if chosen is None:
            continue
        entry = found.setdefault(chosen.id, {
            "machines": [],
            "standard": standards.get(chosen.standard_code, chosen.standard_code) or "Criterio propio",
            "bands": [
                {
                    "status": band.status.name,
                    "color": band.status.color,
                    "min": _plain(band.min_value),
                    "max": _plain(band.max_value),
                }
                for band in chosen.bands
            ],
        })
        entry["machines"].append(machine.name)
    return list(found.values())


def _alignment(request, visits) -> list[dict]:
    from modules.core.infrastructure.routing import installed_codes

    if "alignment" not in installed_codes():
        return []
    from modules.alignment.domain.tolerances import AxisValues, Tolerance, evaluate
    from modules.alignment.infrastructure.models import AlignmentRecord

    records = []
    for row in AlignmentRecord.objects.for_company(request.company_id).filter(service_visit__in=visits):
        tolerance = Tolerance(row.tolerance_parallel_mm, row.tolerance_angular_mm_per_100mm)
        phases = {}
        for phase in ("before", "after"):
            values = AxisValues(*(getattr(row, f"{phase}_{axis}") for axis in
                                  ("angular_h", "parallel_h", "angular_v", "parallel_v")))
            verdict = evaluate(values, tolerance)
            phases[phase] = [
                {"value": "—" if getattr(values, axis) is None else f"{getattr(values, axis):g}",
                 "ok": getattr(verdict, axis)}
                for axis in ("angular_h", "parallel_h", "angular_v", "parallel_v")
            ]
        records.append({
            "coupling": f"{row.driver_label} → {row.driven_label}",
            "rpm": f"{row.rpm:g}",
            "tolerance": (
                f"paralelo {row.tolerance_parallel_mm:g} mm · "
                f"angular {row.tolerance_angular_mm_per_100mm:g} mm/100 mm"
            ),
            "before": phases["before"],
            "after": phases["after"],
        })
    return records


# --------------------------------------------------------------------------
# Informe END — one order (V3-23 AC-02)
# --------------------------------------------------------------------------


def build_end(request, order_id: int) -> dict:
    from modules.diagnostics.models import EquipmentLogEntry
    from modules.measurements.models import Reading
    from modules.media.infrastructure.models import MediaAsset
    from modules.services.models import ServiceOrder, ServiceVisit
    from modules.thresholds.models import TechniqueStatusProfile

    order = (
        ServiceOrder.objects.for_company(request.company_id)
        .select_related("technique", "plant", "provider", "lead_analyst")
        .filter(id=order_id)
        .first()
    )
    if order is None:
        raise NotFound("Esa orden no existe")
    if order.technique.family != "ndt":
        raise ValidationError("El informe END es para órdenes de ensayos no destructivos")
    language = getattr(request, "language", "es")
    visits = list(
        ServiceVisit.objects.for_company(request.company_id)
        .filter(service_order=order)
        .select_related("equipment__asset_group")
        .order_by("equipment__asset_group__name", "equipment__order_in_group", "equipment_id")
    )
    profile = TechniqueStatusProfile.objects.for_company(request.company_id).filter(
        technique=order.technique
    ).first()
    names = {}
    if profile:
        for option in profile.options.select_related("status"):
            names[option.status.code] = option.display_name or option.status.translated("name", language)

    readings: dict[int, list] = {}
    for reading in (
        Reading.objects.for_company(request.company_id)
        .filter(service_visit__in=visits, magnitude__technique=order.technique)
        .select_related("point", "condition_status", "magnitude")
        .order_by("point__number", "id")
    ):
        readings.setdefault(reading.service_visit_id, []).append(reading)
    observations = {
        row.service_visit_id: row.text
        for row in EquipmentLogEntry.objects.for_company(request.company_id)
        .filter(service_visit__in=visits, entry_type="observation")
        .order_by("id")
    }

    width = max((len(rows) for rows in readings.values()), default=0)
    labels = []
    elements, states = [], []
    for visit in visits:
        rows = readings.get(visit.id, [])
        if len(rows) == width and not labels:
            labels = [row.point.label or f"P{row.point.number}" for row in rows]
        inaccessible = bool(rows) and all(
            r.value is None and r.not_measured_reason == "no_access" for r in rows
        )
        worst = _worst(r.condition_status for r in rows)
        measured = [r.value for r in rows if r.value is not None]
        higher_is_worse = rows[0].magnitude.higher_is_worse if rows else True
        headline = (max if higher_is_worse else min)(measured) if measured else None
        state = "Inaccesible" if inaccessible else (names.get(worst.code, worst.name) if worst else "")
        states.append(state)
        elements.append({
            "group": visit.equipment.asset_group.name,
            "name": visit.equipment.name,
            "values": [
                "" if r.value is None else f"{r.value:.2f}" for r in rows
            ] + [""] * (width - len(rows)),
            "headline": "" if headline is None else f"{headline:.2f}",
            "state": state,
            "color": worst.color if worst and not inaccessible else "",
            "observation": observations.get(visit.id, ""),
        })
    order_of_states = [names[code] for code in ("operational", "alarm") if code in names]
    order_of_states += ["Inaccesible"] + [names[c] for c in ("shutdown",) if c in names]
    summary = [{"state": state, "count": states.count(state)} for state in order_of_states]

    conclusions = EquipmentLogEntry.objects.for_company(request.company_id).filter(
        service_visit__in=visits, entry_type__in=("conclusion", "recommendation")
    ).select_related("author").order_by("entry_date", "id")
    photos = [
        {"src": embedded(asset), "caption": asset.caption}
        for asset in MediaAsset.objects.for_company(request.company_id).filter(
            owner_type="visit", owner_id__in=[v.id for v in visits]
        ).order_by("created_at")[: MAX_PHOTOS * 2]
    ]
    return {
        "logo": logo(),
        "title": "Informe de ensayos no destructivos",
        "header": {
            "client": _company(request),
            "plant": order.plant.name,
            "order": order.code,
            "client_order": order.client_work_order,
            "technique": order.technique.translated("name", language),
            "provider": order.provider.name if order.provider else "",
            "analyst": order.lead_analyst.get_full_name() if order.lead_analyst else "",
            "dates": _span(order.scheduled_from, order.scheduled_to),
        },
        "labels": labels or [f"P{i + 1}" for i in range(width)],
        "elements": elements,
        "summary": summary,
        "total": len(elements),
        "conclusions": [_entry(row) for row in conclusions],
        "photos": [row for row in photos if row["src"]],
        "indications": _indications(request, [v.equipment_id for v in visits]),
        "filename": f"informe-end-{order.code}"[:120],
    }


def _indications(request, equipment_ids: list[int]) -> list[dict]:
    from modules.core.infrastructure.routing import installed_codes

    if "ut_rollers" not in installed_codes():
        return []
    from modules.media.infrastructure.models import MediaAsset
    from modules.ut_rollers.models import UTIndication

    rows = []
    for row in UTIndication.objects.for_company(request.company_id).filter(
        equipment_id__in=equipment_ids
    ).select_related("equipment__asset_group"):
        photo = MediaAsset.objects.for_company(request.company_id).filter(
            owner_type="ut_indication", owner_id=row.id
        ).first()
        rows.append({
            "element": f"{row.equipment.asset_group.name} · {row.equipment.name}",
            "kind": row.get_kind_display(),
            "length": "—" if row.length_mm is None else f"{row.length_mm:g} mm",
            "depth": "—" if row.depth_mm is None else f"{row.depth_mm:g} mm",
            "position": row.position,
            "photo": embedded(photo),
        })
    return rows


# --------------------------------------------------------------------------
# Resumen mensual por planta (V3-23 AC-03)
# --------------------------------------------------------------------------


def build_monthly(request, plant_id: int, month: str) -> dict:
    from modules.assets.models import Plant
    from modules.diagnostics.models import EquipmentLogEntry
    from modules.measurements.models import Reading
    from modules.services.models import ServiceVisit

    plant = Plant.objects.for_company(request.company_id).filter(id=plant_id).first()
    if plant is None:
        raise NotFound("Esa planta no existe")
    try:
        year, number = (int(part) for part in month.split("-"))
        start, end = date(year, number, 1), date(year, number, monthrange(year, number)[1])
    except ValueError as cause:
        raise ValidationError("El mes va como AAAA-MM") from cause
    language = getattr(request, "language", "es")

    visits = list(
        ServiceVisit.objects.for_company(request.company_id)
        .filter(
            equipment__asset_group__sector__area__plant=plant,
            visited_at__date__gte=start, visited_at__date__lte=end,
        )
        .exclude(service_order__technique__family="internal")
        .select_related("equipment__asset_group", "service_order__technique", "availability_status")
    )
    techniques: dict[str, str] = {}
    touched: dict[tuple[int, str], dict] = {}
    groups: dict[int, str] = {}
    for visit in visits:
        technique = visit.service_order.technique
        techniques[technique.code] = technique.translated("name", language)
        group = visit.equipment.asset_group
        groups[group.id] = group.name
        cell = touched.setdefault((group.id, technique.code), {"worst": None, "off": False})
        if visit.availability_status and not visit.availability_status.measurable:
            cell["off"] = True
    for reading in (
        Reading.objects.for_company(request.company_id)
        .filter(service_visit__in=visits, condition_status__isnull=False)
        .select_related(
            "condition_status", "service_visit__equipment", "service_visit__service_order__technique"
        )
    ):
        visit = reading.service_visit
        key = (visit.equipment.asset_group_id, visit.service_order.technique.code)
        cell = touched[key]
        if cell["worst"] is None or reading.condition_status.severity > cell["worst"].severity:
            cell["worst"] = reading.condition_status

    entries = EquipmentLogEntry.objects.for_company(request.company_id).filter(
        equipment__asset_group_id__in=groups, entry_date__gte=start, entry_date__lte=end,
        entry_type__in=("conclusion", "recommendation"),
    ).select_related("equipment").order_by("entry_date", "id")
    latest: dict[tuple[int, str], str] = {}
    for entry in entries:
        latest[(entry.equipment.asset_group_id, entry.entry_type)] = entry.text

    codes = sorted(techniques)
    rows, per_technique = [], {code: [] for code in codes}
    for group_id, name in sorted(groups.items(), key=lambda item: item[1]):
        cells = []
        for code in codes:
            cell = touched.get((group_id, code))
            state = None if cell is None else state_for(
                cell["worst"].code if cell["worst"] else None, visited=True, off=cell["off"]
            )
            per_technique[code].append(state)
            cells.append({"state": LABELS.get(state, "") if state else "—", "key": state or ""})
        rows.append({
            "group": name,
            "cells": cells,
            "conclusion": latest.get((group_id, "conclusion"), ""),
            "recommendation": latest.get((group_id, "recommendation"), ""),
        })
    return {
        "logo": logo(),
        "title": "Resumen mensual de condición",
        "header": {"client": _company(request), "plant": plant.name, "month": start.strftime("%m/%Y")},
        "techniques": [techniques[code] for code in codes],
        "rows": rows,
        "pareto": [
            {"technique": techniques[code],
             "counts": [{"state": LABELS[state], "key": state, "count": pareto(per_technique[code])[state]}
                        for state in STATES]}
            for code in codes
        ],
        "filename": f"resumen-{plant.code}-{month}",
    }


# --------------------------------------------------------------------------
# Informe de correctivos (V3-32 AC-06)
# --------------------------------------------------------------------------


def build_corrective(request, start: date, end: date) -> dict:
    from modules.core.infrastructure.routing import installed_codes

    if "maintenance" not in installed_codes():
        raise NotFound("El módulo de mantenimiento no está instalado")
    from modules.maintenance.models import WorkRecord

    names = dict(WorkRecord.WORK_TYPES)
    rows = []
    for row in (
        WorkRecord.objects.for_company(request.company_id)
        .filter(is_closed=True, shift_date__gte=start, shift_date__lte=end)
        .select_related("asset_group", "equipment")
        .prefetch_related("responsibles__user")
        .order_by("started_at", "id")
    ):
        minutes = row.duration_minutes or 0
        rows.append({
            "group": row.asset_group.name,
            "equipment": row.equipment.name if row.equipment else "",
            "work": " / ".join(names.get(code, code) for code in row.work_types)
            + (f" ({row.other_description})" if row.other_description else ""),
            "start": timezone.localtime(row.started_at).strftime("%d/%m/%Y %H:%M") if row.started_at else "",
            "end": timezone.localtime(row.ended_at).strftime("%d/%m/%Y %H:%M") if row.ended_at else "",
            "duration": f"{minutes // 60} h {minutes % 60:02d} min",
            "responsibles": ", ".join(
                r.external_name or (r.user.get_full_name() if r.user else "") for r in row.responsibles.all()
            ),
            "description": row.description,
        })
    return {
        "logo": logo(),
        "title": "Informe de mantenimiento correctivo",
        "header": {"client": _company(request), "period": _span(start, end)},
        "rows": rows,
        "filename": f"correctivos-{start.isoformat()}-{end.isoformat()}",
    }
