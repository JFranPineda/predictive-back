from modules.core.domain.manifest import Manifest, MenuItem

MANIFEST = Manifest(
    code="core",
    name="Núcleo",
    version="0.1.0",
    summary="Multiempresa, registro de módulos, eventos y auditoría",
    category="Sistema",
    depends=(),
    is_core=True,
    permissions=(
        ("core.manage_modules", "Instalar y desinstalar módulos"),
        ("core.manage_company", "Gestionar la compañía"),
        ("core.view_audit", "Ver la auditoría"),
    ),
    menu=(
        MenuItem(label="Aplicaciones", route="/settings/modules", icon="grid",
                 order=10, parent="settings", permission="core.manage_modules"),
        # No permission: everyone chooses their own language and theme.
        MenuItem(label="Preferencias", route="/settings/language", icon="sliders",
                 order=95, parent="settings"),
    ),
    events_published=("ModuleInstalled", "ModuleUninstalled"),
)
