from modules.core.domain.manifest import Manifest, MenuItem

MANIFEST = Manifest(
    code="maintenance",
    name="Mantenimiento correctivo",
    version="0.1.0",
    summary="Cambio de rodamiento, alineamiento, balanceo: inicio, fin y responsables",
    category="Análisis predictivo",
    depends=("core", "assets", "services", "security", "diagnostics", "alignment"),
    auto_install=True,
    permissions=(
        ("maintenance.add_record", "Registrar mantenimiento correctivo"),
        ("maintenance.view", "Ver mantenimiento correctivo"),
    ),
    menu=(
        MenuItem(label="Mantenimiento", route="/maintenance", icon="wrench",
                 order=34, parent=None, permission="maintenance.view"),
    ),
)
