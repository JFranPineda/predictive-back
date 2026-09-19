from django.urls import path

from modules.measurements.interfaces.catalogue_views import (
    InstrumentDetailView,
    InstrumentListView,
    MagnitudeDetailView,
    MagnitudeListView,
    TechniqueListView,
    UnitDetailView,
    UnitListView,
)
from modules.measurements.interfaces.capture_views import VisitCaptureView
from modules.measurements.interfaces.export_views import RecordExportView
from modules.measurements.interfaces.matrix_views import EquipmentMatrixView
from modules.measurements.interfaces.spectrum_views import (
    SpectrumCollectionView,
    SpectrumCurveView,
    SpectrumDetailView,
)
from modules.measurements.interfaces.views import TrendView

urlpatterns = [
    path("equipments/<int:equipment_id>/trend/", TrendView.as_view(), name="equipment-trend"),
    path(
        "equipments/<int:equipment_id>/matrix/",
        EquipmentMatrixView.as_view(),
        name="equipment-matrix",
    ),
    path(
        "equipments/<int:equipment_id>/matrix/export/",
        RecordExportView.as_view(),
        name="equipment-matrix-export",
    ),
    path(
        "service-visits/<int:visit_id>/readings/bulk/",
        VisitCaptureView.as_view(),
        name="visit-capture",
    ),
    path("spectra/", SpectrumCollectionView.as_view(), name="spectra"),
    path("spectra/<int:spectrum_id>/", SpectrumDetailView.as_view(), name="spectrum-detail"),
    path("spectra/<int:spectrum_id>/curve/", SpectrumCurveView.as_view(), name="spectrum-curve"),
    path("techniques/", TechniqueListView.as_view(), name="techniques"),
    path("units/", UnitListView.as_view(), name="units"),
    path("units/<int:unit_id>/", UnitDetailView.as_view(), name="unit-detail"),
    path("magnitudes/", MagnitudeListView.as_view(), name="magnitudes"),
    path(
        "magnitudes/<int:magnitude_id>/",
        MagnitudeDetailView.as_view(),
        name="magnitude-detail",
    ),
    path("instruments/", InstrumentListView.as_view(), name="instruments"),
    path(
        "instruments/<int:instrument_id>/",
        InstrumentDetailView.as_view(),
        name="instrument-detail",
    ),
]
