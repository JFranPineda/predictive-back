from modules.core.domain.manifest import Manifest, MenuItem

MANIFEST = Manifest(
    code="licensing",
    name="Licencias y clientes",
    version="0.1.0",
    summary="Registro de clientes, base de datos on premise y llaves de licencia",
    category="Sistema",
    depends=("core",),
    is_core=True,
    permissions=(
        ("licensing.view_status", "Ver el estado de la licencia"),
        ("licensing.manage_tenant", "Gestionar clientes y sus bases de datos"),
        ("licensing.issue_license", "Emitir y revocar licencias"),
    ),
    menu=(
        MenuItem(label="Licencia", route="/settings/license", icon="key",
                 order=90, parent="settings", permission="licensing.view_status"),
    ),
)
