"""Creating and editing the catalogue from the UI.

Everything a company configures — its standards, the service types each one
judges, its statuses and its limits — is data, not a deployment. The rules that
keep that data coherent live in the domain and are called from here.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.core.domain.i18n import SUPPORTED_LANGUAGES
from modules.measurements.models import Magnitude, Technique
from modules.security.application.access import build_actor
from modules.thresholds.domain.entities import (
    Aggregation,
    Band,
    MachineClass as MachineClassVO,
    Scope,
    Standard,
    Status as StatusVO,
    StatusKind,
    ThresholdSet as ThresholdSetVO,
)
from modules.thresholds.domain.errors import (
    OverlappingBands,
    StandardTechniqueMismatch,
)
from modules.thresholds.domain.services import validate_bands, validate_standard_for_magnitude
from modules.thresholds.models import (
    MachineClass,
    Status,
    ThresholdBand,
    ThresholdSet,
    ThresholdStandard,
)


class PermissionedView(APIView):
    permission_classes = [IsAuthenticated]
    required_permission = ""

    def require(self, request) -> None:
        actor = build_actor(request.user, request.company_id)
        if not actor.has(self.required_permission):
            raise PermissionDenied(f"Falta el permiso {self.required_permission}")


def _slug(value: str) -> str:
    cleaned = "".join(c if c.isalnum() else "_" for c in (value or "").strip().lower())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_")


def _names(payload: dict, fallback: str = "") -> dict[str, str]:
    names = payload.get("names") or {}
    cleaned = {
        language: str(value).strip()
        for language, value in names.items()
        if language in SUPPORTED_LANGUAGES and str(value).strip()
    }
    if not cleaned and fallback:
        cleaned = {"es": fallback}
    return cleaned


def _decimal(raw) -> Decimal | None:
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw).replace(",", "."))
    except InvalidOperation as exc:
        raise ValidationError(f"'{raw}' no es un número") from exc


def _standard_payload(row: ThresholdStandard, language: str) -> dict:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.translated("name", language),
        "names": row.translations.get("name") or {},
        "source": row.source,
        "description": row.description,
        "is_builtin": row.is_builtin,
        "is_active": row.is_active,
        "techniques": [
            {"code": t.code, "name": t.translated("name", language)} for t in row.techniques.all()
        ],
        "machine_classes": [
            {"id": mc.id, "code": mc.code, "name": mc.name, "description": mc.description}
            for mc in row.machine_classes.all()
        ],
        "set_count": row.sets.count(),
    }


class StandardCollectionView(PermissionedView):
    required_permission = "thresholds.manage_standard"

    @transaction.atomic
    def post(self, request):
        self.require(request)
        language = getattr(request, "language", "es")
        name = (request.data.get("name") or "").strip()
        if not name:
            raise ValidationError("El nombre es obligatorio")

        code = _slug(request.data.get("code") or name)
        if ThresholdStandard.objects.for_company(request.company_id).filter(code=code).exists():
            raise ValidationError(f"Ya existe una norma con el código '{code}'")

        standard = ThresholdStandard.objects.create(
            company_id=request.company_id,
            code=code,
            name=name,
            source=(request.data.get("source") or "").strip(),
            description=(request.data.get("description") or "").strip(),
            translations={"name": _names(request.data, name)},
            is_builtin=False,
        )
        _apply_techniques(standard, request.data.get("techniques"))
        _apply_machine_classes(standard, request.data.get("machine_classes"))
        return Response(_standard_payload(standard, language), status=201)


class StandardDetailView(PermissionedView):
    required_permission = "thresholds.manage_standard"

    @transaction.atomic
    def patch(self, request, standard_id: int):
        self.require(request)
        language = getattr(request, "language", "es")
        standard = _get_standard(request, standard_id)

        for field in ("name", "source", "description"):
            if field in request.data:
                setattr(standard, field, (request.data.get(field) or "").strip())
        if "names" in request.data:
            standard.translations = {
                **standard.translations,
                "name": _names(request.data, standard.name),
            }
        if "is_active" in request.data:
            standard.is_active = bool(request.data["is_active"])
        standard.save()

        if "techniques" in request.data:
            _apply_techniques(standard, request.data.get("techniques"))
        if "machine_classes" in request.data:
            _apply_machine_classes(standard, request.data.get("machine_classes"))
        return Response(_standard_payload(standard, language))

    def delete(self, request, standard_id: int):
        self.require(request)
        standard = _get_standard(request, standard_id)
        if standard.is_builtin:
            raise ValidationError("Una norma de fábrica no se elimina; desactívala")
        if standard.sets.exists():
            # Deleting it would orphan every limit that cites it, and with them
            # the explanation of why an equipment got its status.
            raise ValidationError(
                f"La norma tiene {standard.sets.count()} juegos de umbrales asociados"
            )
        standard.delete()
        return Response(status=204)


def _get_standard(request, standard_id: int) -> ThresholdStandard:
    standard = (
        ThresholdStandard.objects.for_company(request.company_id)
        .filter(id=standard_id)
        .prefetch_related("techniques", "machine_classes")
        .first()
    )
    if standard is None:
        raise ValidationError("La norma no existe")
    return standard


def _apply_techniques(standard: ThresholdStandard, codes) -> None:
    if codes is None:
        return
    techniques = list(Technique.objects.filter(code__in=list(codes)))
    missing = set(codes) - {t.code for t in techniques}
    if missing:
        raise ValidationError(f"Técnicas desconocidas: {', '.join(sorted(missing))}")
    standard.techniques.set(techniques)


def _apply_machine_classes(standard: ThresholdStandard, rows) -> None:
    if rows is None:
        return
    keep = []
    for order, row in enumerate(rows):
        name = (row.get("name") or "").strip()
        if not name:
            continue
        code = _slug(row.get("code") or name)
        machine_class, _ = MachineClass.objects.update_or_create(
            standard=standard,
            code=code,
            defaults={
                "name": name,
                "description": (row.get("description") or "").strip(),
                "order": order,
            },
        )
        keep.append(machine_class.id)
    # Classes the user removed in the form, unless something still cites them.
    stale = standard.machine_classes.exclude(id__in=keep)
    for machine_class in stale:
        if machine_class.sets.exists():
            raise ValidationError(
                f"La clase '{machine_class.name}' tiene umbrales asociados"
            )
    stale.delete()


class StatusCollectionView(PermissionedView):
    required_permission = "thresholds.manage_status"

    def post(self, request):
        self.require(request)
        language = getattr(request, "language", "es")
        name = (request.data.get("name") or "").strip()
        kind = request.data.get("kind")
        if not name:
            raise ValidationError("El nombre es obligatorio")
        if kind not in {k.value for k in StatusKind}:
            raise ValidationError("kind debe ser 'condition' o 'availability'")

        code = _slug(request.data.get("code") or name)
        if Status.objects.for_company(request.company_id).filter(code=code).exists():
            raise ValidationError(f"Ya existe un estado con el código '{code}'")

        status = Status.objects.create(
            company_id=request.company_id,
            code=code,
            name=name,
            kind=kind,
            severity=int(request.data.get("severity") or 0),
            color=request.data.get("color") or "#888888",
            requires_action=bool(request.data.get("requires_action")),
            is_terminal=bool(request.data.get("is_terminal")),
            # An availability status exists to explain a missing value.
            measurable=bool(request.data.get("measurable")) if kind == "availability" else True,
            translations={"name": _names(request.data, name)},
        )
        return Response({
            "id": status.id, "code": status.code, "name": status.translated("name", language),
            "kind": status.kind, "severity": status.severity, "color": status.color,
            "measurable": status.measurable, "requires_action": status.requires_action,
            "is_terminal": status.is_terminal, "names": status.translations.get("name") or {},
        }, status=201)


class ThresholdSetCollectionView(PermissionedView):
    required_permission = "thresholds.manage_set"

    @transaction.atomic
    def post(self, request):
        self.require(request)
        return Response(_save_set(request, None), status=201)


class ThresholdSetDetailView(PermissionedView):
    required_permission = "thresholds.manage_set"

    @transaction.atomic
    def patch(self, request, set_id: int):
        self.require(request)
        existing = ThresholdSet.objects.for_company(request.company_id).filter(id=set_id).first()
        if existing is None:
            raise ValidationError("El juego de umbrales no existe")
        return Response(_save_set(request, existing))

    def delete(self, request, set_id: int):
        self.require(request)
        existing = ThresholdSet.objects.for_company(request.company_id).filter(id=set_id).first()
        if existing is None:
            raise ValidationError("El juego de umbrales no existe")
        # Readings freeze the set that judged them, so the history keeps its
        # explanation; deactivating is the honest way to retire a criterion.
        existing.is_active = False
        existing.save(update_fields=["is_active", "updated_at"])
        return Response({"id": existing.id, "is_active": False})


def _save_set(request, existing: ThresholdSet | None) -> dict:
    company_id = request.company_id
    data = request.data

    magnitude_code = data.get("magnitude_code") or (existing.magnitude_code if existing else None)
    magnitude = Magnitude.objects.filter(code=magnitude_code).select_related("technique").first()
    if magnitude is None:
        raise ValidationError(f"La medida '{magnitude_code}' no existe")

    standard = None
    standard_code = data.get("standard_code")
    if standard_code:
        standard = (
            ThresholdStandard.objects.for_company(company_id)
            .filter(code=standard_code)
            .prefetch_related("techniques")
            .first()
        )
        if standard is None:
            raise ValidationError(f"La norma '{standard_code}' no existe")
        try:
            validate_standard_for_magnitude(
                _standard_vo(standard), magnitude.code, magnitude.technique.code
            )
        except StandardTechniqueMismatch as exc:
            raise ValidationError(str(exc)) from exc

    machine_class = None
    if data.get("machine_class_code") and standard is not None:
        machine_class = MachineClass.objects.filter(
            standard=standard, code=data["machine_class_code"]
        ).first()
        if machine_class is None:
            raise ValidationError("Esa clase de máquina no pertenece a la norma elegida")

    scope = data.get("scope") or (existing.scope if existing else "global")
    if scope not in {s.name.lower() for s in Scope}:
        raise ValidationError(f"Ámbito desconocido: {scope}")

    bands_payload = data.get("bands")
    statuses = {
        row.code: row
        for row in Status.objects.for_company(company_id).filter(kind="condition")
    }

    target = existing or ThresholdSet(company_id=company_id)
    target.standard = standard
    target.machine_class = machine_class
    target.scope = scope
    target.scope_ref_id = str(data["scope_ref_id"]) if data.get("scope_ref_id") else None
    target.magnitude_code = magnitude.code
    target.unit_code = data.get("unit_code") or magnitude.default_unit.code
    target.aggregation = data.get("aggregation") or magnitude.default_aggregation
    target.valid_from = data.get("valid_from") or (
        existing.valid_from if existing else _today()
    )
    target.valid_to = data.get("valid_to") or None
    target.rationale = (data.get("rationale") or "").strip()
    target.is_active = bool(data.get("is_active", True))
    if existing is None:
        target.author = request.user
    else:
        target.version = existing.version + 1
    target.save()

    if bands_payload is not None:
        _replace_bands(target, bands_payload, statuses)

    return _set_payload(target, getattr(request, "language", "es"))


def _replace_bands(threshold_set: ThresholdSet, rows, statuses) -> None:
    if not rows:
        raise ValidationError("Un juego de umbrales necesita al menos una banda")

    bands: list[Band] = []
    prepared = []
    for order, row in enumerate(rows):
        status = statuses.get(row.get("status_code"))
        if status is None:
            raise ValidationError(
                f"'{row.get('status_code')}' no es un estado de condición de esta compañía"
            )
        minimum = _decimal(row.get("min_value"))
        maximum = _decimal(row.get("max_value"))
        if minimum is not None and maximum is not None and minimum >= maximum:
            raise ValidationError(f"La banda '{status.code}' tiene el mínimo por encima del máximo")
        prepared.append((status, minimum, maximum, order))
        bands.append(
            Band(
                status=StatusVO(
                    code=status.code, name=status.name, kind=StatusKind.CONDITION,
                    severity=status.severity, color=status.color,
                ),
                min_value=minimum,
                max_value=maximum,
            )
        )

    candidate = ThresholdSetVO(
        id=threshold_set.id,
        magnitude_code=threshold_set.magnitude_code,
        unit_code=threshold_set.unit_code,
        aggregation=Aggregation(threshold_set.aggregation),
        scope=Scope[threshold_set.scope.upper()],
        scope_ref_id=threshold_set.scope_ref_id,
        bands=tuple(bands),
        valid_from=threshold_set.valid_from,
    )
    try:
        validate_bands(candidate)
    except OverlappingBands as exc:
        raise ValidationError(str(exc)) from exc

    threshold_set.bands.all().delete()
    ThresholdBand.objects.bulk_create([
        ThresholdBand(
            threshold_set=threshold_set, status=status,
            min_value=minimum, max_value=maximum, order=order,
        )
        for status, minimum, maximum, order in prepared
    ])


def _standard_vo(row: ThresholdStandard) -> Standard:
    return Standard(
        code=row.code,
        name=row.name,
        source=row.source,
        machine_classes=tuple(
            MachineClassVO(code=mc.code, name=mc.name, description=mc.description)
            for mc in row.machine_classes.all()
        ),
        techniques=tuple(t.code for t in row.techniques.all()),
        is_builtin=row.is_builtin,
    )


def _set_payload(row: ThresholdSet, language: str) -> dict:
    from modules.thresholds.interfaces.views import _scope_label

    return {
        "id": row.id,
        "scope": row.scope,
        "scope_ref_id": row.scope_ref_id,
        "scope_label": _scope_label(row, language),
        "magnitude_code": row.magnitude_code,
        "unit_code": row.unit_code,
        "aggregation": row.aggregation,
        "machine_class": row.machine_class.name if row.machine_class else "",
        "standard": (
            {"code": row.standard.code, "name": row.standard.translated("name", language)}
            if row.standard else None
        ),
        "bands": [
            {
                "status": {
                    "id": band.status.id, "code": band.status.code,
                    "name": band.status.translated("name", language),
                    "kind": band.status.kind, "severity": band.status.severity,
                    "color": band.status.color, "measurable": band.status.measurable,
                    "requires_action": band.status.requires_action,
                },
                "min_value": str(band.min_value) if band.min_value is not None else None,
                "max_value": str(band.max_value) if band.max_value is not None else None,
            }
            for band in row.bands.select_related("status").all()
        ],
        "valid_from": row.valid_from.isoformat(),
        "valid_to": row.valid_to.isoformat() if row.valid_to else None,
        "version": row.version,
        "rationale": row.rationale,
        "author_name": row.author.get_full_name() if row.author else None,
    }


def _today():
    from django.utils import timezone

    return timezone.now().date()
