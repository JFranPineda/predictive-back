from modules.core.domain.manifest import Manifest, MenuItem

MANIFEST = Manifest(
    code="measurements",
    name="Mediciones",
    version="0.1.0",
    summary="Puntos, magnitudes, unidades, lecturas y tendencias. Base de todas las técnicas",
    category="Análisis predictivo",
    depends=("core", "assets", "thresholds"),
    auto_install=True,
    permissions=(
        ("measurements.view_reading", "Ver lecturas"),
        ("measurements.add_reading", "Registrar lecturas"),
        ("measurements.edit_reading", "Corregir lecturas"),
        ("measurements.export", "Exportar mediciones"),
    ),
    menu=(
        MenuItem(label="Mediciones", route="/measurements", icon="activity", order=30,
                 permission="measurements.view_reading"),
    ),
    events_published=("ReadingRecorded",),
    fixtures=("units.yaml", "techniques.yaml", "magnitudes.yaml"),
)
