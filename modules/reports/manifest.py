from modules.core.domain.manifest import Manifest, MenuItem

MANIFEST = Manifest(
    code="reports",
    name="Informes MPd y END",
    version="0.2.0",
    summary="Informe MPd por conjunto, informe END por orden, resumen mensual y correctivos, en PDF y Excel",
    category="Operación",
    depends=("core", "assets", "thresholds", "measurements", "services", "diagnostics", "media"),
    auto_install=True,
    permissions=(
        ("reports.view", "Ver reportes"),
        ("reports.create", "Crear reportes"),
        ("reports.issue", "Emitir reportes al cliente"),
    ),
    menu=(
        MenuItem(label="Informes MPd / END", route="/reports", icon="file-text", order=16, parent=None,
                 permission="reports.view"),
    ),
)
