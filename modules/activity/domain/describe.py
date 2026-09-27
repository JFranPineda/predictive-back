"""What a request did, told in one line a manager can read (Q20).

Pure python: the observer hands over the method, the path and what the body
carried; this names the event and writes its description. The resource names
are the ones the screens use, so "PATCH /service-orders/12/" reads "Modificó
la orden de servicio #12".
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

# The kinds the log filters by, in the order the screen offers them.
KINDS = (
    "login",
    "login_failed",
    "logout",
    "navigation",
    "click",
    "create",
    "update",
    "delete",
    "upload",
    "action",
    "denied",
)

KIND_LABELS = {
    "login": "Inicio de sesión",
    "login_failed": "Acceso fallido",
    "logout": "Cierre de sesión",
    "navigation": "Navegación",
    "click": "Clic",
    "create": "Alta",
    "update": "Modificación",
    "delete": "Baja",
    "upload": "Subida de archivo",
    "action": "Acción",
    "denied": "Rechazado",
}

# One noun per URL segment, singular, as the screens call it.
RESOURCES = {
    "alignment-records": "registro de alineamiento",
    "alignment-scales": "escala de alineamiento",
    "analysts": "analista",
    "areas": "área",
    "asset-group-kinds": "tipo de conjunto",
    "asset-groups": "conjunto",
    "authorship": "autoría del informe",
    "corrective": "correctivo",
    "entries": "anotación",
    "equipments": "equipo",
    "fault-modes": "modo de falla",
    "faults": "falla",
    "groups": "conjunto",
    "indications": "incidencia",
    "instruments": "instrumento",
    "jobs": "servicio",
    "journals": "medición de muñones",
    "log-entries": "anotación de bitácora",
    "magnitudes": "magnitud",
    "markers": "marcador",
    "measurement-trains": "tren de medición",
    "media": "archivo",
    "modules": "módulo",
    "nameplate": "placa de datos",
    "observations": "observación de campo",
    "orders": "orden",
    "participants": "participante",
    "photos": "foto",
    "plants": "planta",
    "points": "punto de medición",
    "readings": "lectura",
    "reports": "informe",
    "roles": "rol",
    "rollers": "rodillo",
    "sectors": "sector",
    "service-orders": "orden de servicio",
    "service-providers": "proveedor de servicio",
    "service-visits": "visita de servicio",
    "sheet": "hoja de espesores",
    "signatures": "firma",
    "spectra": "espectro",
    "standards": "norma",
    "statuses": "estado",
    "surveys": "levantamiento topográfico",
    "techniques": "técnica",
    "thermograms": "termograma",
    "threshold-sets": "juego de umbrales",
    "topography-elements": "elemento de topografía",
    "units": "unidad",
    "users": "usuario",
    "work-records": "registro de mantenimiento",
    "workdays": "jornada",
}

# A final segment that is a verb, not a resource: "POST …/workdays/3/close/".
ACTIONS = {
    "close": ("Cerró", "cerrar"),
    "reopen": ("Reabrió", "reabrir"),
    "open": ("Abrió", "abrir"),
    "sign": ("Firmó", "firmar"),
    "unlock": ("Desbloqueó", "desbloquear"),
    "start": ("Inició", "iniciar"),
    "install": ("Instaló", "instalar"),
    "uninstall": ("Desinstaló", "desinstalar"),
    "upgrade": ("Actualizó", "actualizar"),
    "issue": ("Emitió", "emitir"),
    "export": ("Exportó", "exportar"),
    "import": ("Importó", "importar"),
    "bootstrap": ("Preparó", "preparar"),
    "impersonate": ("Suplantó a", "suplantar a"),
}

VERBS = {
    "POST": ("Creó", "crear"),
    "PUT": ("Reemplazó", "reemplazar"),
    "PATCH": ("Modificó", "modificar"),
    "DELETE": ("Eliminó", "eliminar"),
}
KIND_OF_METHOD = {"POST": "create", "PUT": "update", "PATCH": "update", "DELETE": "delete"}

# Never named in a description, even as a field that changed.
SECRET_FIELDS = frozenset(
    {
        "password",
        "new_password",
        "old_password",
        "token",
        "refresh",
        "access",
        "secret",
        "code",
    }
)

LOGIN_PATHS = ("auth/login", "auth/code-login")

# What an uploaded file belongs to, as `media/` names its owner.
OWNERS = {
    "visit": "visita",
    "point": "punto de medición",
    "equipment": "equipo",
    "asset_group": "conjunto",
    "alignment_record": "registro de alineamiento",
    "topography_survey": "levantamiento topográfico",
    "topography_element": "elemento de topografía",
    "ut_indication": "incidencia UT",
    "service_job": "servicio",
    "service_order": "orden de servicio",
    "field_observation": "observación de campo",
}

# Resources whose id in the path is a code, not a number: "modules/workday/install".
CODE_IDS = frozenset({"modules"})

REFUSALS = {
    400: "datos no válidos",
    401: "sin sesión",
    403: "sin permiso",
    404: "no existe",
    409: "en conflicto",
    423: "jornada cerrada",
    428: "falta el inicio firmado del servicio",
}

DESCRIPTION_LIMIT = 300


@dataclass(frozen=True, slots=True)
class Described:
    kind: str
    event: str
    description: str
    object_type: str = ""
    object_id: str = ""


def describe_request(
    *,
    method: str,
    path: str,
    status: int,
    fields: Iterable[str] = (),
    files: Iterable[str] = (),
    login_email: str = "",
    owner: tuple[str, str] | None = None,
) -> Described | None:
    """None for what is not an event: reads, refreshes, the log's own posts."""
    method = method.upper()
    route = _route(path)
    if route is None or method not in VERBS:
        return None
    if route[:1] == ["activity"] or "/".join(route[:2]) == "auth/refresh":
        return None

    if "/".join(route[:2]) in LOGIN_PATHS:
        who = login_email or "sin correo"
        if status < 400:
            return Described("login", "Inicio de sesión", f"Entró al sistema ({who})")
        return Described("login_failed", "Acceso fallido", f"Intento de acceso rechazado para {who}")

    resource, object_id, action, parent = _parse(route)
    noun = RESOURCES.get(resource, resource.replace("-", " "))
    where = f" de {RESOURCES.get(parent[0], parent[0])} #{parent[1]}" if parent else ""
    files = [name for name in files if name]
    changed = sorted(field for field in fields if field.lower() not in SECRET_FIELDS)

    subject = _subject(noun, object_id)
    if status >= 400:
        infinitive = ACTIONS[action][1] if action else VERBS[method][1]
        reason = REFUSALS.get(status, f"error {status}")
        return _cut(
            Described(
                "denied",
                "Rechazado",
                f"No se pudo {infinitive} {subject}{where} ({reason})",
                resource,
                object_id,
            )
        )

    if action:
        past = ACTIONS[action][0]
        return _cut(Described("action", past, f"{past} {subject}{where}", resource, object_id))

    if files and method in ("POST", "PUT", "PATCH"):
        names = ", ".join(f"«{name}»" for name in files[:3]) + ("…" if len(files) > 3 else "")
        target = f" ({subject}{where})"
        if owner and owner[0] in OWNERS:
            target = f" ({OWNERS[owner[0]]} #{owner[1]})" if owner[1] else f" ({OWNERS[owner[0]]})"
        return _cut(Described("upload", "Subió archivo", f"Subió {names}{target}", resource, object_id))

    kind = KIND_OF_METHOD[method]
    detail = f" · campos: {', '.join(changed[:8])}" if changed and kind == "update" else ""
    return _cut(
        Described(
            kind,
            KIND_LABELS[kind],
            f"{VERBS[method][0]} {subject}{where}{detail}",
            resource,
            object_id,
        )
    )


@dataclass(frozen=True, slots=True)
class ClientEvent:
    kind: str
    event: str
    description: str
    path: str


def clean_client_events(raw: Iterable[dict], limit: int = 100) -> list[ClientEvent]:
    """What the browser sends: clicks and page changes only, trimmed. Anything
    else is dropped — the browser does not get to write a "delete" row."""
    events = []
    for item in list(raw)[:limit]:
        if not isinstance(item, dict) or item.get("kind") not in ("click", "navigation", "logout"):
            continue
        label = " ".join(str(item.get("label") or "").split())[:120]
        path = str(item.get("path") or "")[:200]
        kind = item["kind"]
        if kind == "click":
            if not label:
                continue
            description = f"Clic en «{label}» ({path})" if path else f"Clic en «{label}»"
            events.append(ClientEvent("click", "Clic", description, path))
        elif kind == "navigation":
            title = f" · {label}" if label else ""
            events.append(ClientEvent("navigation", "Navegación", f"Abrió {path}{title}", path))
        else:
            events.append(ClientEvent("logout", "Cierre de sesión", "Salió del sistema", path))
    return events


def _route(path: str) -> list[str] | None:
    marker = "/api/v1/"
    if marker not in path:
        return None
    return [segment for segment in path.split(marker, 1)[1].split("/") if segment]


def _parse(route: list[str]) -> tuple[str, str, str, tuple[str, str] | None]:
    """(resource, id, action, parent) of `a/1/b/2/close`: the last resource,
    its id, the verb if the path ends in one, and the resource above it."""
    action = route[-1] if route[-1] in ACTIONS and len(route) > 1 else ""
    body = route[:-1] if action else route
    pairs: list[tuple[str, str]] = []
    for segment in body:
        if pairs and not pairs[-1][1] and (segment.isdigit() or pairs[-1][0] in CODE_IDS):
            pairs[-1] = (pairs[-1][0], segment)
        elif not segment.isdigit():
            pairs.append((segment, ""))
    if not pairs:
        return route[0], "", action, None
    resource, object_id = pairs[-1]
    parent = pairs[-2] if len(pairs) > 1 and pairs[-2][1] else None
    return resource, object_id, action, parent


def _subject(noun: str, object_id: str) -> str:
    if not object_id:
        return noun
    return f"{noun} #{object_id}" if object_id.isdigit() else f"{noun} «{object_id}»"


def _cut(described: Described) -> Described:
    if len(described.description) <= DESCRIPTION_LIMIT:
        return described
    return Described(
        described.kind,
        described.event,
        described.description[: DESCRIPTION_LIMIT - 1] + "…",
        described.object_type,
        described.object_id,
    )
