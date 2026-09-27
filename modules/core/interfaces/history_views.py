"""The archived months of a log, listed and downloaded.

The screens show a fortnight (`core.domain.history`); this is where the rest
of the log is, so nobody has to ask the sysadmin for it.
"""

from __future__ import annotations

from django.http import FileResponse, Http404
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.core.domain.history import WINDOW_DAYS
from modules.core.infrastructure.history import archive_all, folder, root, source_by_code, sources
from modules.core.infrastructure.models import Company, HistoryFile
from modules.security.infrastructure.access import build_actor


class HistoryView(APIView):
    """`GET history/?source=activity` — the months already on disk.

    `POST history/` files everything older than the window right now; the
    same work a nightly `manage.py history archive` does.
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request):
        actor = build_actor(request.user, request.company_id)
        wanted = request.query_params.get("source")
        readable = [
            source
            for source in sources()
            if actor.has(source.permission) and (not wanted or source.code == wanted)
        ]
        if wanted and not readable:
            raise PermissionDenied("Ese registro no existe o no puedes verlo")

        company = Company.objects.get(id=request.company_id)
        files = HistoryFile.objects.for_company(request.company_id).filter(
            source__in=[source.code for source in readable]
        )
        by_source: dict[str, list] = {}
        for row in files:
            by_source.setdefault(row.source, []).append(row)

        return Response(
            {
                "window_days": WINDOW_DAYS,
                "sources": [
                    {
                        "code": source.code,
                        "label": source.label,
                        "folder": str(folder(company, source)),
                        "files": [_payload(row) for row in by_source.get(source.code, [])],
                    }
                    for source in readable
                ],
            }
        )

    def post(self, request):
        actor = build_actor(request.user, request.company_id)
        if not actor.has("core.archive_history"):
            raise PermissionDenied("Falta el permiso core.archive_history")
        company = Company.objects.get(id=request.company_id)
        return Response({"results": archive_all(company)})


class HistoryFileView(APIView):
    """`GET history/<source>/<period>/` — that month, as the CSV on disk."""

    permission_classes = (IsAuthenticated,)

    def get(self, request, source: str, period: str):
        found = source_by_code(source)
        actor = build_actor(request.user, request.company_id)
        if found is None or not actor.has(found.permission):
            raise PermissionDenied("Ese registro no existe o no puedes verlo")

        stored = (
            HistoryFile.objects.for_company(request.company_id)
            .filter(source=source, period=period)
            .first()
        )
        path = root() / stored.path if stored else None
        if path is None or not path.exists():
            raise Http404("Ese mes no está archivado")
        return FileResponse(
            path.open("rb"), as_attachment=True, filename=f"{source}-{period}.csv"
        )


def _payload(row: HistoryFile) -> dict:
    return {
        "period": row.period,
        "path": row.path,
        "rows": row.rows,
        "size": row.size,
        "last_at": row.last_at.isoformat() if row.last_at else None,
    }
