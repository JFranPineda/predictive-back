from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.thresholds.models import Status, ThresholdSet, ThresholdStandard


class StatusListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        language = getattr(request, "language", "es")
        queryset = Status.objects.for_company(request.company_id)
        if request.query_params.get("kind"):
            queryset = queryset.filter(kind=request.query_params["kind"])
        return Response([
            {
                "id": row.id, "code": row.code, "name": row.translated("name", language),
                "kind": row.kind, "severity": row.severity, "color": row.color,
                "measurable": row.measurable, "requires_action": row.requires_action,
                "is_terminal": row.is_terminal,
                "names": row.translations.get("name") or {},
            }
            for row in queryset
        ])


class StatusDetailView(APIView):
    """Name and colour are configurable: T12 asks for it, and a company that
    repaints ALARMA should not need a release."""

    permission_classes = [IsAuthenticated]

    def patch(self, request, status_id: int):
        from rest_framework.exceptions import PermissionDenied

        from modules.core.domain.i18n import SUPPORTED_LANGUAGES
        from modules.security.application.access import build_actor

        actor = build_actor(request.user, request.company_id)
        if not actor.has("thresholds.manage_status"):
            raise PermissionDenied("No puedes administrar estados")

        row = Status.objects.for_company(request.company_id).filter(id=status_id).first()
        if row is None:
            return Response({"type": "not_found", "status": 404}, status=404)

        colour = request.data.get("color")
        if colour:
            if not _is_hex(colour):
                return Response({"type": "invalid_color", "status": 400}, status=400)
            row.color = colour

        names = request.data.get("names") or {}
        if names:
            stored = row.translations.get("name") or {}
            stored.update({
                language: str(value).strip()
                for language, value in names.items()
                if language in SUPPORTED_LANGUAGES and str(value).strip()
            })
            row.translations = {**row.translations, "name": stored}
            row.name = stored.get("es") or row.name

        row.save(update_fields=["color", "name", "translations", "updated_at"])
        language = getattr(request, "language", "es")
        return Response({
            "id": row.id, "code": row.code, "name": row.translated("name", language),
            "kind": row.kind, "severity": row.severity, "color": row.color,
            "measurable": row.measurable, "requires_action": row.requires_action,
            "is_terminal": row.is_terminal,
            "names": row.translations.get("name") or {},
        })


def _is_hex(value: str) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("#")
        and len(value) in (4, 7)
        and all(c in "0123456789abcdefABCDEF" for c in value[1:])
    )


class StandardListView(APIView):
    """Configuración global > Normas."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        language = getattr(request, "language", "es")
        queryset = (
            ThresholdStandard.objects.for_company(request.company_id)
            .prefetch_related("machine_classes", "techniques")
            .order_by("name")
        )
        return Response([
            {
                "id": row.id, "code": row.code, "name": row.translated("name", language),
                "names": row.translations.get("name") or {},
                "source": row.source, "description": row.description,
                "is_builtin": row.is_builtin, "is_active": row.is_active,
                "techniques": [
                    {"code": t.code, "name": t.translated("name", language)}
                    for t in row.techniques.all()
                ],
                "machine_classes": [
                    {"id": mc.id, "code": mc.code, "name": mc.name, "description": mc.description}
                    for mc in row.machine_classes.all()
                ],
                "set_count": row.sets.count(),
            }
            for row in queryset
        ])


class ThresholdSetListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        language = getattr(request, "language", "es")
        queryset = (
            ThresholdSet.objects.for_company(request.company_id)
            .select_related("standard", "machine_class", "author")
            .prefetch_related("bands__status")
        )
        for field in ("magnitude", "scope", "aggregation"):
            value = request.query_params.get(field)
            if value:
                queryset = queryset.filter(**{f"{field.replace('magnitude', 'magnitude_code')}": value})

        return Response([
            {
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
                    for band in row.bands.all()
                ],
                "valid_from": row.valid_from.isoformat(),
                "valid_to": row.valid_to.isoformat() if row.valid_to else None,
                "version": row.version,
                "rationale": row.rationale,
                "author_name": row.author.get_full_name() if row.author else None,
            }
            for row in queryset
        ])


def _scope_label(row: ThresholdSet, language: str) -> str:
    if row.scope == "global":
        return "—"
    if row.scope == "equipment_type":
        return row.scope_ref_id or ""
    if row.scope == "equipment":
        from modules.assets.models import Equipment

        equipment = Equipment.objects.filter(id=row.scope_ref_id).first()
        return str(equipment) if equipment else row.scope_ref_id or ""
    return row.scope_ref_id or ""
