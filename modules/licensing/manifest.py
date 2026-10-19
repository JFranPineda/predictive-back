from modules.core.domain.manifest import Manifest, MenuItem

MANIFEST = Manifest(
    code="licensing",
    name="Licencias y clientes",
    version="0.4.0",
    summary="Registro de clientes, base de datos on premise y llaves de licencia",
    category="Sistema",
    depends=("core",),
    is_core=True,
    permissions=(
        ("licensing.view_status", "Ver el estado de la licencia"),
        ("licensing.manage_tenant", "Gestionar clientes y sus bases de datos"),
        ("licensing.issue_license", "Emitir y revocar licencias"),
        ("licensing.renew_license", "Renovar la licencia: pedirla y cargar el archivo"),
        ("licensing.export_data", "Exportar todos los datos del cliente"),
    ),
    menu=(
        MenuItem(label="Licencia", route="/settings/license", icon="key",
                 order=90, parent="settings", permission="licensing.view_status"),
    ),
)
