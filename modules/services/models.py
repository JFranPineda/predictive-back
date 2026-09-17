"""Django only auto-imports `<app>.models`, and in this layout the ORM lives in
`infrastructure/`. This re-export is the one line of glue that keeps both true:
the models stay in the infrastructure layer, and Django still finds them."""

from modules.services.infrastructure.models import ServicePlan, PlanLine, ServiceOrder, ServiceVisit, VisitParticipant  # noqa: F401

__all__ = ["ServicePlan", "PlanLine", "ServiceOrder", "ServiceVisit", "VisitParticipant"]
