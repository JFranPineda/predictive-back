from modules.core.domain.manifest import Manifest, MenuItem

MANIFEST = Manifest(
    code="security",
    name="Usuarios y permisos",
    version="0.3.0",
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
        ("security.manage_access_code", "Emitir y revocar códigos de acceso de técnicos"),
    ),
    menu=(
        MenuItem(label="Usuarios", route="/settings/users", icon="users",
                 order=5, parent="settings", permission="security.view_user"),
        MenuItem(label="Permisos", route="/settings/roles", icon="shield",
                 order=6, parent="settings", permission="security.manage_role"),
        MenuItem(label="Auditoría", route="/settings/audit", icon="history",
                 order=7, parent="settings", permission="core.view_audit"),
    ),
)
