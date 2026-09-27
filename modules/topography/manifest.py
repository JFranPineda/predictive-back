from modules.core.domain.manifest import Manifest

MANIFEST = Manifest(
    code="topography",
    name="Topografía",
    version="0.2.0",
    summary=(
        "Levantamiento por conjunto: esquema, plano con notas, y por polín los cuatro cuadros de "
        "paralelismo y nivelación con su foto y los desplazamientos en mm"
    ),
    category="Análisis predictivo",
    depends=("core", "assets", "services", "security", "media"),
    auto_install=True,
    permissions=(
        ("topography.view", "Ver topografía"),
        ("topography.manage", "Registrar topografía"),
    ),
    # No screen of its own: it lives embedded in the topography visit's own
    # detail page, so there is nothing to put in the menu.
    menu=(),
)
