"""Django only auto-imports `<app>.models`, and in this layout the ORM lives in
`infrastructure/`. This re-export is the one line of glue that keeps both true:
the models stay in the infrastructure layer, and Django still finds them."""

from modules.assets.infrastructure.models import Plant, Area, Sector, AssetGroup, Equipment, MeasurementPoint  # noqa: F401

__all__ = ["Plant", "Area", "Sector", "AssetGroup", "Equipment", "MeasurementPoint"]
