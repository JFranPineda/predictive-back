"""Django only auto-imports `<app>.models`, and in this layout the ORM lives in
`infrastructure/`. This re-export is the one line of glue that keeps both true:
the models stay in the infrastructure layer, and Django still finds them."""

from modules.operating_data.infrastructure.models import (  # noqa: F401
    OperatingParameter,
    OperatingReading,
)

__all__ = ["OperatingParameter", "OperatingReading"]
