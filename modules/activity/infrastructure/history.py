"""The activity log as an archived log (manifest `history_source`).

The same columns the CSV export writes, so a month on disk and a month
exported from the screen are the same file.
"""

from __future__ import annotations

from django.utils import timezone

from modules.core.infrastructure.history import HistorySource


def source() -> HistorySource:
    return HistorySource(
        code="activity",
        label="Registro de actividad",
        permission="activity.view",
        model="activity.ActivityEvent",
        at_field="at",
        header=("Fecha", "Hora", "Usuario", "Evento", "Descripción", "Ruta", "IP"),
        row=_row,
    )


def _row(event) -> list[str]:
    local = timezone.localtime(event.at)
    return [
        local.strftime("%d/%m/%Y"),
        local.strftime("%H:%M:%S"),
        event.user_label or "—",
        event.event,
        event.description,
        event.path,
        event.ip or "",
    ]
