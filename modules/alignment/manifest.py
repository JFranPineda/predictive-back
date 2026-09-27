from modules.core.domain.manifest import Manifest, MenuItem

MANIFEST = Manifest(
    code="alignment",
    name="Alineamiento",
    version="0.3.0",
    summary=(
        "Alineamiento láser antes/después, formato SKF: ocho valores, estado del equipo según "
        "la norma e imágenes del alineador por conjunto"
    ),
    category="Análisis predictivo",
    depends=("core", "assets", "services", "security", "diagnostics", "thresholds"),
    auto_install=True,
    permissions=(
        ("alignment.view", "Ver alineamientos"),
        ("alignment.manage", "Registrar y editar alineamientos"),
    ),
    menu=(
        MenuItem(label="Alineamiento", route="/alignment", icon="align-center-vertical",
                 order=32, parent=None, permission="alignment.view"),
    ),
    # The SKF norma and its RPM scale, for companies that had none (Q10).
    on_install="modules.alignment.infrastructure.setup.install",
)
