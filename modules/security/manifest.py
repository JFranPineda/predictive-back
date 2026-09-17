from modules.core.domain.manifest import Manifest, MenuItem

MANIFEST = Manifest(
    code="security",
    name="Usuarios y permisos",
    version="0.2.0",
    summary="Usuarios internos y externos, roles, permisos por módulo y alcance por planta o área",
    category="Sistema",
    depends=("core",),
    is_core=True,
    permissions=(
        ("security.view_user", "Ver usuarios"),
        ("security.manage_user", "Crear y editar usuarios"),
        ("security.invite_external", "Invitar inspectores externos"),
        ("security.manage_role", "Gestionar roles y permisos"),
        ("security.manage_scope", "Restringir usuarios a plantas o áreas"),
        ("security.impersonate", "Suplantar a un usuario"),
    ),
    menu=(
        MenuItem(label="Usuarios", route="/settings/users", icon="users",
                 order=5, parent="settings", permission="security.view_user"),
    ),
    fixtures=("default_roles.yaml",),
)
