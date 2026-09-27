"""Filing the part of a log that the screen no longer shows.

A module declares its log in the manifest (`history_source`); this archiver
writes everything older than the window into
`data/history/<empresa>/<registro>/<AAAA-MM>.csv` and deletes the rows it
filed. The screen keeps a fortnight, the disk keeps everything, and the path
is plain enough to find without the application.

Only rows that reached the file are deleted, and the file is written before
the delete: a crash between the two repeats a month, never loses one.
"""

from __future__ import annotations

import csv
import importlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from modules.core.domain.history import archived_before, period_of

# Rows filed per run. Bounded so the first archive of a table nobody pruned
# cannot hold a million rows in memory; the command loops until it is done.
BATCH = 20_000


@dataclass(frozen=True, slots=True)
class HistorySource:
    """One log that is archived: where its rows are, and how they read."""

    code: str
    label: str
    permission: str
    model: str
    """`app_label.ModelName`, as `apps.get_model` takes it."""
    at_field: str
    header: tuple[str, ...]
    row: Callable[[object], list[str]]


@cache
def _declared() -> tuple[tuple[str, HistorySource], ...]:
    from modules.core.infrastructure.discovery import discover_manifests

    found = []
    for manifest in discover_manifests():
        if not manifest.history_source:
            continue
        module_path, _, name = manifest.history_source.rpartition(".")
        found.append((manifest.code, getattr(importlib.import_module(module_path), name)()))
    return tuple(found)


def sources() -> list[HistorySource]:
    """The logs of the modules this tenant installed."""
    from modules.core.infrastructure.routing import installed_codes

    installed = installed_codes()
    return [source for code, source in _declared() if code in installed]


def source_by_code(code: str) -> HistorySource | None:
    return next((source for source in sources() if source.code == code), None)


def root() -> Path:
    return Path(settings.HISTORY_ROOT)


def folder(company, source: HistorySource) -> Path:
    return root() / company.code / source.code


def archive(company, source: HistorySource, today: date | None = None, limit: int = BATCH) -> dict:
    """Files this log's rows older than the window. Returns what it wrote.

    At most `limit` rows per run, oldest first, so the first archive of a
    table nobody ever pruned does not have to fit in memory.
    """
    from django.apps import apps

    from modules.core.infrastructure.models import HistoryFile

    cutoff = archived_before(today or timezone.localdate())
    model = apps.get_model(source.model)
    old = model.objects.filter(company=company, **{f"{source.at_field}__lt": _start_of(cutoff)})

    months: dict[str, list] = {}
    for row in old.order_by(source.at_field, "id")[:limit]:
        months.setdefault(_period(row, source), []).append(row)

    written = 0
    for period, rows in sorted(months.items()):
        path = folder(company, source) / f"{period}.csv"
        _append(path, source, rows)
        stored, _ = HistoryFile.objects.get_or_create(
            company=company, source=source.code, period=period, defaults={"path": ""}
        )
        stored.path = str(path.relative_to(root()))
        stored.rows += len(rows)
        stored.size = path.stat().st_size
        stored.last_at = getattr(rows[-1], source.at_field)
        stored.save()
        model.objects.filter(id__in=[row.id for row in rows]).delete()
        written += len(rows)
    return {"source": source.code, "archived": written, "pending": old.count()}


def archive_all(company, today: date | None = None) -> list[dict]:
    return [archive(company, source, today) for source in sources()]


def _append(path: Path, source: HistorySource, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh = not path.exists()
    # Excel reads UTF-8 only with the BOM, and these files are opened there.
    with path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        if fresh:
            writer.writerow(source.header)
        for row in rows:
            writer.writerow(source.row(row))


def _period(row, source: HistorySource) -> str:
    return period_of(timezone.localtime(getattr(row, source.at_field)).date())


def _start_of(day: date):
    from datetime import datetime, time

    return timezone.make_aware(datetime.combine(day, time.min))
