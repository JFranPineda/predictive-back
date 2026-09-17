from modules.core.domain.manifest import Manifest, MenuItem

MANIFEST = Manifest(
    code="ultrasound",
    name="Análisis de ultrasonido",
    version="0.1.0",
    summary="Lecturas en dB, capturas del equipo, audio heterodino y rutas de fugas",
    category="Análisis predictivo",
    depends=('core', 'assets', 'measurements', 'thresholds', 'media'),
    auto_install=False,
    permissions=(
        ("ultrasound.view", "Ver ultrasonido"),
        ("ultrasound.add_reading", "Registrar ultrasonido"),
    ),
    menu=(
        MenuItem(label="Ultrasonido", route="/ultrasound", icon="radio", order=70, parent=None, permission='ultrasound.view'),
    ),
    provides_techniques=('ultrasound',),
)
