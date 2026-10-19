"""The full export (v4 Phase 4): the exit guarantee of the contract.

Whatever the state of the licence, the customer takes everything: every table
as a workbook, a SQL script that restores it, and the original files, in one
ZIP with a manifest that says what is inside and a README that says how to
open it. From the screen it is prepared in a background thread and kept until
the next one replaces it; from the console it is written where asked.
"""

from __future__ import annotations

import json
import logging
import tempfile
import threading
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from modules.licensing.domain.export import EXCLUDED_TABLES, REDACTED_COLUMNS

logger = logging.getLogger(__name__)

# A thread that died with its process (a restart, a deploy) leaves its row
# "running" forever; past this, it counts as interrupted and may be retried.
STALE_AFTER = timedelta(hours=2)

README = """PREDICTIVE — exportación completa de {tenant}
Generada el {created} (UTC), versión {version}.

Contenido
- datos.xlsx: una hoja por tabla de la base, con todas sus filas. Si una tabla
  pasa del millón de filas, sigue en otra hoja: «tabla (2)», «tabla (3)»…
  Excel corta a 32 767 caracteres una celda más larga; el script SQL no corta
  nada.
- {sql}: el esquema y todos los datos. Se restaura en una base vacía:
    createdb predictive_restaurada
    psql -d predictive_restaurada -f {sql}
- archivos/: las fotos, termogramas y espectros originales.
- manifiesto.json: cada tabla con sus filas y sus hojas, y los archivos.

No viajan, a propósito: las contraseñas de los usuarios (un archivo que se
envía por correo o en una memoria no debe llevarlas; cada usuario restaurado
pone una nueva) y las sesiones abiertas.

PREDICTIVE nunca borra ni cifra sus datos, tampoco cuando la suscripción vence:
consultar y exportar siguen disponibles siempre.
"""


@dataclass(frozen=True, slots=True)
class ExportSummary:
    path: Path
    tables: int
    rows: int
    files: int
    size: int


def export_tenant(tenant_code: str, destination: Path) -> ExportSummary:
    """Everything the tenant owns, into one ZIP under `destination`."""
    from modules.licensing.infrastructure.context import ensure_registered
    from modules.licensing.infrastructure.renewal_facts import program_version
    from modules.licensing.infrastructure.tenant_dump import add_files, write_sql, write_workbook

    alias = ensure_registered(tenant_code)
    created = datetime.now(UTC)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f"predictive-{tenant_code}-{created:%Y%m%d-%H%M%S}.zip"
    with tempfile.TemporaryDirectory(dir=destination, prefix=".export-") as work:
        work_dir = Path(work)
        tables = write_workbook(alias, work_dir / "datos.xlsx")
        sql = write_sql(alias, work_dir)
        partial = work_dir / "export.zip"
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            archive.write(work_dir / "datos.xlsx", "datos.xlsx")
            archive.write(work_dir / sql, sql)
            files, missing = add_files(archive, alias)
            archive.writestr("manifiesto.json", json.dumps({
                "tenant": tenant_code,
                "created_at": created.isoformat(),
                "program_version": program_version(),
                "sql": sql,
                "tables": tables,
                "files": files,
                "missing_files": missing,
                "excluded_tables": sorted(EXCLUDED_TABLES),
                "redacted_columns": sorted(f"{table}.{column}" for table, column in REDACTED_COLUMNS),
            }, ensure_ascii=False, indent=2))
            archive.writestr("LEEME.txt", README.format(
                tenant=tenant_code, created=f"{created:%Y-%m-%d %H:%M}", version=program_version(), sql=sql,
            ))
        partial.replace(target)
    return ExportSummary(
        path=target, tables=len(tables), rows=sum(entry["rows"] for entry in tables.values()),
        files=files, size=target.stat().st_size,
    )


def start_export(tenant_code: str, *, requested_by: str):
    """One at a time per tenant: asking again while one is being prepared
    returns that one."""
    from modules.licensing.infrastructure.models import Tenant, TenantExport

    current = latest_export(tenant_code)
    if current is not None and current.status in ("pending", "running"):
        return current
    tenant = Tenant.objects.get(code=tenant_code)
    export = TenantExport.objects.create(tenant=tenant, requested_by=requested_by)
    threading.Thread(target=_run, args=(export.pk,), daemon=True, name=f"export-{tenant_code}").start()
    return export


def latest_export(tenant_code: str):
    from django.utils import timezone

    from modules.licensing.infrastructure.models import TenantExport

    export = TenantExport.objects.filter(tenant__code=tenant_code).first()
    stale = export is not None and export.created_at < timezone.now() - STALE_AFTER
    if stale and export.status in ("pending", "running"):
        export.status, export.error = "failed", "Se interrumpió (el servidor se reinició): vuelve a pedirla."
        export.save(update_fields=["status", "error"])
    return export


def _run(export_id: int) -> None:
    from django.conf import settings
    from django.db import connections
    from django.utils import timezone

    from modules.licensing.infrastructure.models import TenantExport

    export = TenantExport.objects.select_related("tenant").get(pk=export_id)
    try:
        export.status = "running"
        export.save(update_fields=["status"])
        summary = export_tenant(export.tenant.code, Path(settings.EXPORT_ROOT) / export.tenant.code)
        export.status, export.path, export.size = "done", str(summary.path), summary.size
        export.rows, export.files, export.finished_at = summary.rows, summary.files, timezone.now()
        export.save()
        _forget_older_exports(export)
    except Exception as exc:
        # A background thread has nobody to raise to: the row says what happened.
        logger.exception("export %s failed", export_id)
        export.status, export.error, export.finished_at = "failed", str(exc)[:300], timezone.now()
        export.save(update_fields=["status", "error", "finished_at"])
    finally:
        connections.close_all()


def _forget_older_exports(latest) -> None:
    """Each export is a copy of everything, files included, and the disk is
    the server's scarce resource: keep the newest. Removes the previous export
    archives only — copies we made, never the customer's data."""
    for older in latest.tenant.exports.exclude(pk=latest.pk).exclude(path=""):
        Path(older.path).unlink(missing_ok=True)  # previous export archive, a copy we made
        older.path = ""
        older.save(update_fields=["path"])
