from modules.core.domain.manifest import Manifest, MenuItem

MANIFEST = Manifest(
    code="reports",
    name="Reportes",
    version="0.1.0",
    summary="Reportes de inspección predictiva con snapshot congelado y PDF",
    category="Operación",
    depends=('core', 'assets', 'measurements', 'diagnostics', 'media'),
    auto_install=True,
    permissions=(
        ("reports.view", "Ver reportes"),
        ("reports.create", "Crear reportes"),
        ("reports.issue", "Emitir reportes al cliente"),
    ),
    menu=(
        MenuItem(label="Reportes", route="/reports", icon="file-text", order=95, parent=None, permission='reports.view'),
    ),
)
