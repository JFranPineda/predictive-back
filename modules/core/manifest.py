from modules.core.domain.manifest import Manifest, MenuItem

MANIFEST = Manifest(
    code="core",
    name="Núcleo",
    version="0.2.0",
    summary="Multiempresa, registro de módulos, eventos y auditoría",
    category="Sistema",
    depends=(),
    is_core=True,
    permissions=(
        ("core.manage_modules", "Instalar y desinstalar módulos"),
        ("core.manage_company", "Gestionar la compañía"),
        ("core.view_audit", "Ver la auditoría"),
        ("core.archive_history", "Archivar en disco los registros antiguos"),
    ),
    menu=(
        MenuItem(label="Aplicaciones", route="/settings/modules", icon="grid",
                 order=10, parent="settings", permission="core.manage_modules"),
        # No permission: everyone chooses their own language and theme.
        MenuItem(label="Preferencias", route="/settings/language", icon="sliders",
                 order=95, parent="settings"),
    ),
    history_source="modules.core.infrastructure.audit_history.source",
    events_published=("ModuleInstalled", "ModuleUninstalled"),
)
