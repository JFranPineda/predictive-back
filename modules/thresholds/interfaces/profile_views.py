"""Each service's set of states — Estados → «Condiciones por servicio».

A technique's status profile is the vocabulary of that service: the condition
states its normas may grade into (alignment: Operativo, Observación, Alarma,
Parada) and the availability states a technician may declare instead of a
value (Apagado, Fuera de servicio). The profile can also rename a state for
that service only — UT's "Medio" is the plant's Alarma.

Two services never share a profile, so "conjunto de condiciones 01 para
alineamiento" and "02 para vibraciones" are two profiles. Two sets of limits
for the same service — vibration with and without isolators — are not two
services: they are two classes of the same norma (Umbrales).
"""

from __future__ import annotations

from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.core.infrastructure.audit import record
from modules.core.infrastructure.routing import installed_codes
from modules.licensing.infrastructure.context import current_alias
from modules.security.infrastructure.access import build_actor
from modules.thresholds.infrastructure.models import (
    Status,
    TechniqueStatusOption,
    TechniqueStatusProfile,
    ThresholdBand,
)


class StatusProfileListView(APIView):
    """`GET status-profiles/` — every service of an installed module, with
    the states it offers, in its order."""

    permission_classes = (IsAuthenticated,)

    def get(self, request):
        language = getattr(request, "language", "es")
        return Response([_payload(request, technique, language) for technique in _techniques()])


class StatusProfileDetailView(APIView):
    """`PUT status-profiles/<technique>/` with `{"options": [{"status": id,
    "display_name": ""}, …]}` in the order the service lists them."""

    permission_classes = (IsAuthenticated,)

    def put(self, request, technique_code: str):
        if not build_actor(request.user, request.company_id).has("thresholds.manage_status"):
            raise PermissionDenied("Falta el permiso thresholds.manage_status")
        technique = next((row for row in _techniques() if row.code == technique_code), None)
        if technique is None:
            raise ValidationError("Ese servicio no existe o su módulo no está instalado")

        wanted = request.data.get("options") or []
        ids = [int(option["status"]) for option in wanted]
        statuses = {
            row.id: row for row in Status.objects.for_company(request.company_id).filter(id__in=ids)
        }
        if len(statuses) != len(set(ids)):
            raise ValidationError("Algún estado no existe")
        if not any(statuses[i].kind == "condition" for i in ids):
            raise ValidationError("El servicio necesita al menos un estado de condición")
        _keep_graded(request, technique, {statuses[i].code for i in ids})

        with transaction.atomic(using=current_alias()):
            profile, _ = TechniqueStatusProfile.objects.get_or_create(
                company_id=request.company_id, technique=technique
            )
            before = list(profile.options.values_list("status__code", flat=True))
            profile.options.all().delete()
            TechniqueStatusOption.objects.bulk_create(
                TechniqueStatusOption(
                    profile=profile,
                    status_id=int(option["status"]),
                    order=position,
                    display_name=(option.get("display_name") or "").strip()[:60],
                )
                for position, option in enumerate(wanted)
            )
            record(request, "thresholds.profile_changed", object_type="technique", object_id=technique.code,
                   before={"estados": before}, after={"estados": [statuses[i].code for i in ids]})
        return Response(_payload(request, technique, getattr(request, "language", "es")))


def _techniques():
    from modules.measurements.models import Technique

    installed = installed_codes()
    return [row for row in Technique.objects.order_by("name") if row.module_code in installed]


def _keep_graded(request, technique, kept: set[str]) -> None:
    """A state a norma of this service already grades into stays: dropping it
    would leave those bands pointing at a state the service no longer has."""
    from modules.measurements.models import Magnitude

    magnitudes = Magnitude.objects.filter(technique=technique).values_list("code", flat=True)
    used = set(
        ThresholdBand.objects.filter(
            threshold_set__company_id=request.company_id,
            threshold_set__is_active=True,
            threshold_set__magnitude_code__in=list(magnitudes),
        ).values_list("status__code", flat=True)
    )
    missing = used - kept
    if missing:
        names = Status.objects.for_company(request.company_id).filter(code__in=missing).order_by("severity")
        raise ValidationError(
            f"Hay umbrales de este servicio que califican en {', '.join(row.name for row in names)}. "
            "Cámbialos en Umbrales antes de quitar esos estados."
        )


def _payload(request, technique, language: str) -> dict:
    options = (
        TechniqueStatusOption.objects.filter(
            profile__company_id=request.company_id, profile__technique=technique
        )
        .select_related("status")
        .order_by("order", "id")
    )
    return {
        "technique": {"code": technique.code, "name": technique.translated("name", language)},
        "options": [
            {
                "status": option.status_id,
                "code": option.status.code,
                "kind": option.status.kind,
                "name": option.status.translated("name", language),
                "display_name": option.display_name,
                "color": option.status.color,
            }
            for option in options
        ],
    }
