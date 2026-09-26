"""Django needs the models on the app's `models` module; the models stay in
the infrastructure layer."""

from modules.ut_rollers.infrastructure.models import UTIndication

__all__ = ["UTIndication"]
