from modules.core.domain.manifest import Manifest, MenuItem

MANIFEST = Manifest(
    code="oil_analysis",
    name="Análisis de aceite",
    version="0.1.0",
    summary="Muestras de lubricante y aceite dieléctrico, resultados de laboratorio y tendencias",
    category="Análisis predictivo",
    depends=("core", "assets", "measurements", "thresholds", "media"),
    auto_install=False,
    permissions=(
        ("oil_analysis.view", "Ver análisis de aceite"),
        ("oil_analysis.add_sample", "Registrar muestras"),
        ("oil_analysis.enter_results", "Cargar resultados de laboratorio"),
        ("oil_analysis.import", "Importar resultados del laboratorio"),
    ),
    menu=(
        MenuItem(label="Aceite", route="/oil-analysis", icon="droplet", order=75,
                 permission="oil_analysis.view"),
    ),
    provides_techniques=("oil_analysis", "insulating_oil"),
)
