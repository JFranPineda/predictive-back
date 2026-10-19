"""How much of the plan is in use (V3-36): the bar on the licence screen."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.licensing.application.license_service import plan_usage
from modules.licensing.infrastructure.keys import trusted_keys


class LicenseUsageView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        from modules.assets.infrastructure.plan_counts import equipment_in_plan, plants_in_plan

        tenant = getattr(request, "tenant", None)
        if tenant is None:
            return Response({"resources": []})
        counts = {
            "equipment": equipment_in_plan(request.company_id),
            "plants": plants_in_plan(request.company_id),
        }
        rows = [
            plan_usage(tenant.code, resource, used, keys=trusted_keys())
            for resource, used in counts.items()
        ]
        return Response({
            "resources": [
                {"resource": row.resource, "used": row.used, "allowed": row.allowed,
                 "near_limit": row.near_limit}
                for row in rows
            ],
        })
