"""The audit trail as an archived log (manifest `history_source`)."""

from __future__ import annotations

from django.utils import timezone

from modules.core.infrastructure.history import HistorySource


def source() -> HistorySource:
    return HistorySource(
        code="audit",
        label="Auditoría",
        permission="core.view_audit",
        model="core.AuditLog",
        at_field="at",
        header=("Fecha", "Hora", "Usuario", "Acción", "Objeto", "ID", "Antes", "Después", "IP"),
        row=_row,
    )


def _row(entry) -> list[str]:
    local = timezone.localtime(entry.at)
    return [
        local.strftime("%d/%m/%Y"),
        local.strftime("%H:%M:%S"),
        entry.actor.get_full_name() if entry.actor else "—",
        entry.action,
        entry.object_type,
        entry.object_id,
        _plain(entry.before),
        _plain(entry.after),
        entry.ip or "",
    ]


def _plain(values: dict | None) -> str:
    """The change as a person reads it, not as JSON: the file is opened in
    Excel, where a nested brace is noise."""
    if not values:
        return ""
    return " · ".join(f"{key}: {value}" for key, value in values.items())
