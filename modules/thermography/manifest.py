from modules.core.domain.manifest import Manifest, MenuItem

MANIFEST = Manifest(
    code="thermography",
    name="Análisis de termografía",
    version="0.1.0",
    summary="Termogramas con matriz radiométrica preservada, ΔT y clasificación por norma",
    category="Análisis predictivo",
    depends=('core', 'assets', 'measurements', 'thresholds', 'media'),
    auto_install=False,
    permissions=(
        ("thermography.view", "Ver termografía"),
        ("thermography.add_reading", "Registrar termografía"),
    ),
    menu=(
        MenuItem(label="Termografía", route="/thermography", icon="thermometer", order=80, parent=None, permission='thermography.view'),
    ),
    provides_techniques=('thermography',),
)
