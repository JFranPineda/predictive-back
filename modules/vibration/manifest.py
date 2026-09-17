from modules.core.domain.manifest import Manifest, MenuItem

MANIFEST = Manifest(
    code="vibration",
    name="Análisis de vibraciones",
    version="0.1.0",
    summary="Espectros, formas de onda, frecuencias de falla y tendencias vibracionales",
    category="Análisis predictivo",
    depends=('core', 'assets', 'measurements', 'thresholds', 'media', 'blueprints'),
    auto_install=False,
    permissions=(
        ("vibration.view", "Ver vibraciones"),
        ("vibration.add_reading", "Registrar vibraciones"),
        ("vibration.diagnose", "Diagnosticar espectros"),
        ("vibration.import", "Importar del instrumento"),
    ),
    menu=(
        MenuItem(label="Vibraciones", route="/vibration", icon="waveform", order=60, parent=None, permission='vibration.view'),
    ),
    provides_techniques=('vibration',),
)
