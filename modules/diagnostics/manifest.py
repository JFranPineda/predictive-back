from modules.core.domain.manifest import Manifest, MenuItem

MANIFEST = Manifest(
    code="diagnostics",
    name="Diagnóstico",
    version="0.1.0",
    summary="Diario fechado del equipo, modos de falla y recomendaciones con seguimiento",
    category="Análisis predictivo",
    depends=('core', 'assets', 'measurements'),
    auto_install=True,
    permissions=(
        ("diagnostics.view", "Ver diagnósticos"),
        ("diagnostics.add_entry", "Registrar hallazgos"),
        ("diagnostics.close_recommendation", "Cerrar recomendaciones"),
    ),
    menu=(
        MenuItem(label="Diagnóstico", route="/diagnostics", icon="stethoscope", order=90, parent=None, permission='diagnostics.view'),
    ),
)
