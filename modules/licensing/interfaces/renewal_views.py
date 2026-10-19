"""Renewing from /settings/license (v4 Phase 3): the request to send, and the
`.lic` that comes back. Under /api/v1/license/, so they answer even when the
licence already blocks: an expired installation must be able to renew."""

from __future__ import annotations

from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.core.infrastructure.audit import record
from modules.licensing.application.renewal import build_request, import_licence
from modules.licensing.domain.renewal import RenewalRejectedError
from modules.licensing.infrastructure.keys import trusted_keys

MAX_LICENCE_BYTES = 16_000


def _renewing_tenant(request):
    """Only on-premise renews (P3-c): a hosted tenant we renew ourselves."""
    from modules.security.infrastructure.access import build_actor

    if not build_actor(request.user, request.company_id).has("licensing.renew_license"):
        raise PermissionDenied("Falta el permiso licensing.renew_license")
    tenant = getattr(request, "tenant", None)
    if tenant is None or tenant.deployment != "on_premise":
        raise NotFound("La renovación por archivo es para instalaciones on-premise.")
    return tenant


class LicenseRenewalRequestView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        tenant = _renewing_tenant(request)
        try:
            renewal = build_request(tenant.code, keys=trusted_keys())
        except RenewalRejectedError as exc:
            raise ValidationError(str(exc)) from exc
        return Response({"text": renewal.text()})


class LicenseRenewView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        tenant = _renewing_tenant(request)
        upload = request.FILES.get("licence")
        if upload is not None:
            if upload.size > MAX_LICENCE_BYTES:
                raise ValidationError("Ese archivo no es una licencia: es demasiado grande.")
            text = upload.read().decode("utf-8", errors="replace")
        else:
            text = str(request.data.get("licence", ""))
        try:
            outcome = import_licence(tenant.code, text, keys=trusted_keys(), source="archivo")
        except RenewalRejectedError as exc:
            raise ValidationError(str(exc)) from exc
        record(request, "license.renewed", object_type="licence", object_id=outcome.license_id,
               after={"status": outcome.status, "valid_until": outcome.valid_until.isoformat()})
        return Response({
            "status": outcome.status,
            "license_id": outcome.license_id,
            "valid_until": outcome.valid_until.isoformat(),
        })
