"""Reading a whole tenant database out: every table to a workbook, a SQL
script that restores it, and the original files (v4 Phase 4).

It reads tables, not models: whatever is in the customer's database travels,
including tables no screen shows. Only what `domain/export.py` excludes or
redacts stays behind.
"""

from __future__ import annotations

import base64
import json
import sqlite3
import zipfile
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from django.apps import apps
from django.core.management.color import no_style
from django.db import connections, router, transaction
from django.db.migrations.recorder import MigrationRecorder
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

from modules.licensing.domain.export import (
    EXCEL_MAX_ROWS,
    EXCLUDED_TABLES,
    REDACTED_COLUMNS,
    redact,
    sheet_name,
    split_rows,
)

EXCEL_MAX_CELL = 32_767
FETCH = 2_000
INSERT_BATCH = 500
# PostgreSQL type OIDs whose values come back as Python objects.
JSON_OID, JSONB_OID = 114, 3802


def tenant_tables(alias: str) -> list[str]:
    connection = connections[alias]
    with connection.cursor() as cursor:
        return sorted(t for t in connection.introspection.table_names(cursor) if t not in EXCLUDED_TABLES)


def write_workbook(alias: str, path: Path) -> dict[str, dict[str, Any]]:
    """One sheet per table, split past Excel's row limit. Returns what went
    where, for the manifest."""
    workbook = Workbook(write_only=True)
    used: set[str] = set()
    written: dict[str, dict[str, Any]] = {}
    for table in tenant_tables(alias):
        columns = [column[0] for column in _columns(alias, table)]
        sheets, count = [], 0
        for part, chunk in enumerate(split_rows(_stream(alias, table), EXCEL_MAX_ROWS), start=1):
            sheet = workbook.create_sheet(sheet_name(table, part, used))
            sheet.append(columns)
            for row in chunk:
                sheet.append([_cell(value) for value in redact(table, columns, row)])
            sheets.append(sheet.title)
            count += len(chunk)
        written[table] = {"rows": count, "sheets": sheets}
    workbook.save(path)
    return written


def write_sql(alias: str, directory: Path) -> str:
    """A script any PostgreSQL (or SQLite, for a development tenant) restores
    into an empty database. Returns its file name."""
    if connections[alias].vendor == "postgresql":
        name = "predictive-postgresql.sql"
        with open(directory / name, "w", encoding="utf-8") as handle:
            _postgresql_script(alias, handle)
    else:
        name = "predictive-sqlite.sql"
        with open(directory / name, "w", encoding="utf-8") as handle:
            _sqlite_script(alias, handle)
    return name


def add_files(archive: zipfile.ZipFile, alias: str) -> tuple[int, list[str]]:
    """The originals: photos, thermograms and spectra. A file that cannot be
    read is listed as missing; it never stops the export."""
    from modules.measurements.infrastructure.models import Spectrum
    from modules.media.infrastructure.local_store import store
    from modules.media.infrastructure.models import MediaAsset

    backend = store()
    sources = (
        ("media", MediaAsset.objects.using(alias).exclude(original_key="").values_list(
            "original_key", flat=True)),
        ("espectros", Spectrum.objects.using(alias).exclude(data_key="").values_list("data_key", flat=True)),
    )
    added, missing = 0, []
    for folder, keys in sources:
        # The content is stored once and shared by every owner of it.
        for key in sorted(set(keys)):
            try:
                payload = backend.get(key)
            except Exception:
                # Local disk or object store, any failure reads the same: missing.
                missing.append(key)
                continue
            archive.writestr(f"archivos/{folder}/{key}", payload)
            added += 1
    return added, missing


def _columns(alias: str, table: str):
    """DB-API descriptions: name first, type second, on every backend. The
    table name comes from introspection, never from input."""
    connection = connections[alias]
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT * FROM {connection.ops.quote_name(table)} LIMIT 0")
        return list(cursor.description)


def _stream(alias: str, table: str):
    """Row by row through a server-side cursor: a table of millions of
    readings never sits in memory whole."""
    connection = connections[alias]
    with transaction.atomic(using=alias), connection.chunked_cursor() as cursor:
        cursor.execute(f"SELECT * FROM {connection.ops.quote_name(table)} ORDER BY 1")
        while chunk := cursor.fetchmany(FETCH):
            yield from chunk


def _cell(value: Any) -> Any:
    """What openpyxl accepts and Excel shows. The SQL script keeps every value
    exact; the workbook is for reading, so a cell past Excel's limit is cut."""
    if isinstance(value, datetime | time) and value.tzinfo is not None:
        value = value.astimezone(UTC) if isinstance(value, datetime) else value
        return value.replace(tzinfo=None)
    if isinstance(value, int | float | Decimal | bool | date | time | timedelta) or value is None:
        return value
    if isinstance(value, dict | list):
        value = json.dumps(value, ensure_ascii=False, default=str)
    elif isinstance(value, bytes | memoryview):
        value = base64.b64encode(bytes(value)).decode()
    return ILLEGAL_CHARACTERS_RE.sub("", str(value))[:EXCEL_MAX_CELL]


def _schema_models(alias: str) -> list:
    tables = set(connections[alias].introspection.table_names())
    models = [
        model for model in apps.get_models()
        if model._meta.managed and not model._meta.proxy
        and router.allow_migrate_model(alias, model) and model._meta.db_table in tables
    ]
    # Restored, the database still knows which migrations it carries.
    return [*models, MigrationRecorder(connections[alias]).Migration]


def _postgresql_script(alias: str, out) -> None:
    from psycopg import ClientCursor
    from psycopg.types.json import Jsonb

    connection = connections[alias]
    connection.ensure_connection()
    models = _schema_models(alias)
    with connection.schema_editor(collect_sql=True, atomic=False) as editor:
        for model in models:
            editor.create_model(model)
        created = len(editor.collected_sql)
    tables, deferred = editor.collected_sql[:created], editor.collected_sql[created:]

    out.write("-- PREDICTIVE: volcado completo del cliente. Restaurar en una base vacía:\n")
    out.write("--   createdb predictive_restaurada\n")
    out.write("--   psql -d predictive_restaurada -f predictive-postgresql.sql\n")
    out.write("BEGIN;\n\n")
    out.writelines(f"{statement}\n" for statement in tables)
    mogrify = ClientCursor(connection.connection).mogrify
    for table in tenant_tables(alias):
        description = _columns(alias, table)
        columns = [column[0] for column in description]
        json_columns = {i for i, c in enumerate(description) if c[1] in (JSON_OID, JSONB_OID)}
        quoted = connection.ops.quote_name(table)
        head = f"INSERT INTO {quoted} ({', '.join(connection.ops.quote_name(c) for c in columns)}) VALUES\n"
        placeholders = "(" + ", ".join(["%s"] * len(columns)) + ")"
        batch: list[str] = []
        for row in _stream(alias, table):
            values = [
                Jsonb(value) if i in json_columns and value is not None else value
                for i, value in enumerate(redact(table, columns, row))
            ]
            batch.append(mogrify(placeholders, values))
            if len(batch) == INSERT_BATCH:
                out.write(head + ",\n".join(batch) + ";\n")
                batch = []
        if batch:
            out.write(head + ",\n".join(batch) + ";\n")
    out.write("\n")
    out.writelines(f"{statement}\n" for statement in deferred)
    out.writelines(f"{statement}\n" for statement in connection.ops.sequence_reset_sql(no_style(), models))
    out.write("COMMIT;\n")


def _sqlite_script(alias: str, out) -> None:
    """A development tenant: SQLite's own dump of a copy, with the same
    exclusions as everywhere else."""
    connection = connections[alias]
    connection.ensure_connection()
    copy = sqlite3.connect(":memory:")
    connection.connection.backup(copy)
    for (table, column), value in REDACTED_COLUMNS.items():
        copy.execute(f'UPDATE "{table}" SET "{column}" = ?', (value,))
    skipped = tuple(f'INSERT INTO "{table}"' for table in EXCLUDED_TABLES)
    out.writelines(f"{statement}\n" for statement in copy.iterdump() if not statement.startswith(skipped))
    copy.close()
