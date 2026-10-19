"""The full export from /settings/license (v4 Phase 4): the administrator
starts it, it is prepared in the background, and downloaded when ready.

Under /api/v1/license/, so the licence never stands in the way: the exit
guarantee holds whatever its state, and for hosted tenants too.
"""

from __future__ import annotations

from pathlib import Path

from django.http import FileResponse
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.core.infrastructure.audit import record
from modules.licensing.application.tenant_export import latest_export, start_export


def _exporting_tenant(request):
    from modules.security.infrastructure.access import build_actor

    if not build_actor(request.user, request.company_id).has("licensing.export_data"):
        raise PermissionDenied("Falta el permiso licensing.export_data")
    tenant = getattr(request, "tenant", None)
    if tenant is None:
        raise NotFound("Sin cliente")
    return tenant


def _payload(export) -> dict:
    if export is None:
        return {"status": "none"}
    return {
        "id": export.pk,
        "status": export.status,
        "size": export.size,
        "rows": export.rows,
        "files": export.files,
        "error": export.error,
        "created_at": export.created_at.isoformat(),
        "finished_at": export.finished_at.isoformat() if export.finished_at else None,
        "downloadable": export.status == "done" and bool(export.path),
    }


class LicenseExportView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        return Response(_payload(latest_export(_exporting_tenant(request).code)))

    def post(self, request):
        tenant = _exporting_tenant(request)
        export = start_export(tenant.code, requested_by=request.user.email)
        record(request, "license.export_started", object_type="export", object_id=export.pk)
        return Response(_payload(export), status=202)


class LicenseExportDownloadView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, export_id: int):
        from modules.licensing.infrastructure.models import TenantExport

        tenant = _exporting_tenant(request)
        export = TenantExport.objects.filter(pk=export_id, tenant__code=tenant.code, status="done").first()
        if export is None or not export.path or not Path(export.path).is_file():
            raise NotFound("Esa exportación ya no está: pide una nueva.")
        record(request, "license.export_downloaded", object_type="export", object_id=export.pk)
        path = Path(export.path)
        return FileResponse(path.open("rb"), as_attachment=True, filename=path.name)
