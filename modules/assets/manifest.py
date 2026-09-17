from modules.core.domain.manifest import Manifest, MenuItem

MANIFEST = Manifest(
    code="assets",
    name="Activos",
    version="0.1.0",
    summary="Plantas, áreas, sectores, conjuntos rotativos, equipos y puntos",
    category="Activos",
    depends=("core",),
    is_core=True,
    permissions=(
        ("assets.view_equipment", "Ver activos"),
        ("assets.manage_equipment", "Crear y editar activos"),
        ("assets.import", "Importar activos desde Excel"),
        ("assets.manage_point", "Gestionar puntos de medición"),
    ),
    menu=(
        MenuItem(label="Activos", route="/assets", icon="factory", order=20,
                 permission="assets.view_equipment"),
    ),
    events_published=("EquipmentStatusChanged",),
)
