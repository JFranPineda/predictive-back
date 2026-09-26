from modules.core.domain.manifest import Manifest, MenuItem

MANIFEST = Manifest(
    code="alignment",
    name="Alineamiento",
    version="0.1.0",
    summary="Alineamiento láser antes/después, formato SKF: dos fases, veredicto por tolerancia",
    category="Análisis predictivo",
    depends=("core", "assets", "services", "security", "diagnostics"),
    auto_install=True,
    permissions=(
        ("alignment.view", "Ver alineamientos"),
        ("alignment.manage", "Registrar y editar alineamientos"),
    ),
    menu=(
        MenuItem(label="Alineamiento", route="/alignment", icon="align-center-vertical",
                 order=32, parent=None, permission="alignment.view"),
    ),
)
