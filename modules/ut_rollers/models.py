"""Django needs the models on the app's `models` module; the models stay in
the infrastructure layer."""

from modules.ut_rollers.infrastructure.models import JournalInspection, RollerGroupReport, UTIndication

__all__ = ["JournalInspection", "RollerGroupReport", "UTIndication"]
