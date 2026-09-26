"""Django needs the models on the app's `models` module; the models stay in
the infrastructure layer."""

from modules.maintenance.infrastructure.models import WorkRecord, WorkRecordResponsible

__all__ = ["WorkRecord", "WorkRecordResponsible"]
