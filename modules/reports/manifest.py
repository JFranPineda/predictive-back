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
    # Two entries, one per family of report: the predictive one (MPd, with its
    # monthly summary and the correctivos) and the non-destructive one (END).
    menu=(
        MenuItem(label="Informes MPd", route="/reports/mpd", icon="file-text", order=16, parent=None,
                 permission="reports.view"),
        MenuItem(label="Informes END", route="/reports/end", icon="file-text", order=17, parent=None,
                 permission="reports.view"),
    ),
)
