from modules.core.domain.manifest import Manifest, MenuItem

MANIFEST = Manifest(
    code="ut_rollers",
    name="END · UT en rodillos",
    version="0.1.0",
    summary="Seis espesores por rodillo, veredicto sobre el mínimo, incidencias y resumen por estado",
    category="Ensayos no destructivos",
    depends=("core", "assets", "thresholds", "measurements", "services", "security", "media", "diagnostics"),
    auto_install=True,
    permissions=(
        ("ut_rollers.view", "Ver UT en rodillos"),
        ("ut_rollers.capture", "Capturar espesores e incidencias de rodillos"),
        ("ut_rollers.manage_rollers", "Dar de alta rodillos en un conjunto"),
    ),
    menu=(
        MenuItem(label="UT en rodillos", route="/ut-rollers", icon="circle-dot",
                 order=35, parent=None, permission="ut_rollers.view"),
    ),
    on_install="modules.ut_rollers.infrastructure.setup.install",
    provides_techniques=("ndt_rollers",),
)
