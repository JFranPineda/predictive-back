from modules.core.domain.manifest import Manifest, MenuItem

MANIFEST = Manifest(
    code="summaries",
    name="Informes",
    version="0.1.0",
    summary="Semáforo de planta por área y sector, y resúmenes por tipo de servicio",
    category="Operación",
    depends=("core", "assets", "measurements", "thresholds"),
    auto_install=True,
    permissions=(
        ("summaries.view", "Ver informes de planta"),
        ("summaries.export", "Exportar informes"),
        ("summaries.manage_palette", "Configurar los colores de los estados"),
    ),
    menu=(
        MenuItem(label="Informes", route="/summaries", icon="layout-dashboard", order=15,
                 permission="summaries.view"),
    ),
    events_subscribed=("EquipmentStatusChanged", "ReadingRecorded"),
)
