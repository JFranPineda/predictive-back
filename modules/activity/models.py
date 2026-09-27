"""Django needs the models on the app's `models` module; the models stay in
the infrastructure layer."""

from modules.activity.infrastructure.models import ActivityEvent

__all__ = ["ActivityEvent"]
