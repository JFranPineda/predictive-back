"""This installation, as the licence sees it: its identity and the three
identifiers it is recognised by.

The identity lives in two places, the control plane and a file in the data
volume, so a reinstall that keeps either one keeps the installation. The
control plane wins when they disagree. Nothing here is allowed to fail a
request: an identifier that cannot be read is simply missing.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import DatabaseError, IntegrityError, connections, transaction

from modules.licensing.domain.installation import InstallationFingerprint, installation_fingerprint
from modules.licensing.infrastructure.context import ensure_registered

logger = logging.getLogger(__name__)


def installation_id() -> str:
    from modules.licensing.infrastructure.models import Installation

    state = read_state()
    record = Installation.objects.filter(pk=1).first()
    if record is None:
        try:
            record, _ = Installation.objects.get_or_create(
                pk=1, defaults={"installation_id": _valid_uuid(state.get("installation_id")) or uuid.uuid4()}
            )
        except IntegrityError:
            # Another worker created it first.
            record = Installation.objects.get(pk=1)
    value = str(record.installation_id)
    if state.get("installation_id") != value:
        write_state({**state, "installation_id": value})
    return value


def observed_installation(tenant_code: str, *, installation: str | None = None) -> InstallationFingerprint:
    """The three identifiers of the installation answering this request."""
    return installation_fingerprint(
        installation or installation_id(),
        pg_system_id(ensure_registered(tenant_code)),
        machine_id(),
    )


def pg_system_id(alias: str) -> str | None:
    """Readable by a plain role through `pg_control_system()` (checked on the
    bench in Phase 0): no extra grant for the customer's IT."""
    connection = connections[alias]
    if connection.vendor != "postgresql":
        return None
    try:
        with transaction.atomic(using=alias), connection.cursor() as cursor:
            cursor.execute("SELECT system_identifier FROM pg_control_system()")
            row = cursor.fetchone()
    except DatabaseError:
        logger.warning("cannot read PostgreSQL's system identifier on %s", alias)
        return None
    return str(row[0]) if row else None


def machine_id() -> str | None:
    try:
        value = Path(settings.MACHINE_ID_FILE).read_text().strip()
    except OSError:
        return None
    return value or None


def read_state() -> dict[str, Any]:
    try:
        data = json.loads(Path(settings.INSTALLATION_FILE).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_state(data: dict[str, Any]) -> None:
    """Atomic: a reader sees the old file or the new one, never half."""
    path = Path(settings.INSTALLATION_FILE)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".installation-")
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
        os.replace(temporary, path)
    except OSError:
        logger.warning("cannot write the installation file %s", path)


def _valid_uuid(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None
