"""Downloads the record of values as a workbook."""

from __future__ import annotations

from datetime import date

from django.http import HttpResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from modules.assets.models import Equipment
from modules.measurements.infrastructure.record_export import (
    ExportBand,
    ExportBlock,
    ExportColumn,
    build_workbook,
)
from modules.measurements.interfaces.matrix_views import EquipmentMatrixView

SIDE_LABELS = {
    "free_end": "LADO LIBRE",
    "coupling_end": "LADO ACOPLE",
    "opposite_coupling": "LADO OPUESTO A ACOPLE",
    "inboard": "INTERIOR",
    "outboard": "EXTERIOR",
    "custom": "GENERAL",
}


class RecordExportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, equipment_id: int):
        # The grid and the workbook must never disagree, so the export reads
        # the same payload the screen does rather than querying again.
        matrix = EquipmentMatrixView().get(request, equipment_id).data
        if "equipment" not in matrix:
            return HttpResponse(status=404)

        operating, labels = _operating(request, matrix["columns"])
        payload = build_workbook(
            equipment=matrix["equipment"],
            columns=[
                ExportColumn(
                    date=column["date"],
                    order_code=column["order_code"],
                    operators=_operators(request, column),
                    operating=_merge(operating, column),
                )
                for column in matrix["columns"]
            ],
            blocks=[_block(block) for block in matrix["blocks"]],
            bands=_bands(request, equipment_id),
            operating_labels=labels,
            title="SERVICIO DE MANTENIMIENTO PREDICTIVO",
        )

        filename = f"registro-{matrix['equipment']['tag']}-{date.today().isoformat()}.xlsx"
        response = HttpResponse(
            payload,
            content_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


def _block(block: dict) -> ExportBlock:
    return ExportBlock(
        title=block["title"],
        unit=block["unit"],
        aggregation=block["aggregation"],
        decimals=block["decimals"],
        rows=tuple(
            {
                "component": row["component"],
                "side_label": SIDE_LABELS.get(row["side"], row["side"].upper()),
                "label": row["label"],
                "values": [cell["value"] if cell else None for cell in row["cells"]],
                # A blank column is a round that does not exist for this point;
                # "--" is one that was not measured. The sheet has always
                # distinguished them and so does the export.
                "missing": [
                    "--" if cell and cell["value"] is None else "" for cell in row["cells"]
                ],
            }
            for row in block["rows"]
        ),
    )


def _merge(operating: dict, column: dict) -> dict[str, str]:
    """Every machine of the train contributes its conditions, and the machine
    that was asked for wins any parameter they share — a running hour counter
    belongs to one machine and must not alternate between two."""
    merged: dict[str, str] = {}
    for visit_id in column["visit_ids"]:
        if visit_id != column["primary_visit_id"]:
            merged.update(operating.get(visit_id, {}))
    merged.update(operating.get(column["primary_visit_id"], {}))
    return merged


def _operators(request, column: dict) -> str:
    from modules.services.models import VisitParticipant

    if not column["visit_ids"]:
        return ""
    initials = VisitParticipant.objects.filter(visit_id__in=column["visit_ids"]).values_list(
        "user__initials", "user__first_name"
    )
    # One round, one signature: "HT / AJ", as the sheet writes it.
    names = {entry[0] or entry[1] for entry in initials if entry[0] or entry[1]}
    return " / ".join(sorted(names))


def _operating(request, columns: list[dict]) -> tuple[dict, dict]:
    from modules.operating_data.models import OperatingReading

    language = getattr(request, "language", "es")
    visit_ids = [visit for column in columns for visit in column["visit_ids"]]
    rows = (
        OperatingReading.objects.for_company(request.company_id)
        .filter(service_visit_id__in=visit_ids)
        .select_related("parameter")
    )
    by_visit: dict[int, dict[str, str]] = {}
    labels: dict[str, str] = {}
    for row in rows:
        labels[row.parameter.code] = (
            f"{row.parameter.translated('name', language)}"
            f"{f' ({row.parameter.unit_code})' if row.parameter.unit_code else ''}"
        )
        if row.value is not None:
            by_visit.setdefault(row.service_visit_id, {})[row.parameter.code] = str(row.value)
    return by_visit, labels


def _bands(request, equipment_id: int) -> list[ExportBand]:
    """The limits actually in force for this equipment, resolved through the
    same cascade that graded the readings."""
    from modules.thresholds.application.evaluation import context_for
    from modules.thresholds.domain.services import resolve
    from modules.thresholds.infrastructure.repositories import DjangoThresholdRepository

    equipment = (
        Equipment.objects.for_company(request.company_id)
        .select_related(
            "asset_group__kind", "applied_standard", "machine_class", "nameplate"
        )
        .filter(id=equipment_id)
        .first()
    )
    if equipment is None:
        return []

    repository = DjangoThresholdRepository(getattr(request, "language", "es"))
    bands: list[ExportBand] = []
    for magnitude_code, aggregation in (("vel_rms", "rms"), ("env_accel", "peak")):
        context = context_for(equipment, magnitude_code, aggregation)
        chosen = resolve(
            repository.candidates(request.company_id, magnitude_code), context, date.today()
        )
        if chosen is None:
            continue
        for band in chosen.bands:
            bands.append(
                ExportBand(
                    status=f"{band.status.name} · {magnitude_code} ({chosen.unit_code})",
                    minimum="—" if band.min_value is None else str(band.min_value),
                    maximum="—" if band.max_value is None else str(band.max_value),
                )
            )
    return bands
