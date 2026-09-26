from modules.core.domain.manifest import Manifest

MANIFEST = Manifest(
    code="topography",
    name="Topografía",
    version="0.1.0",
    summary="Nivelación y paralelismo por elemento, sobre el plano de la máquina",
    category="Análisis predictivo",
    depends=("core", "assets", "services", "security"),
    auto_install=True,
    permissions=(
        ("topography.view", "Ver topografía"),
        ("topography.manage", "Registrar topografía"),
    ),
    # No screen of its own: it lives embedded in the topography visit's own
    # detail page, so there is nothing to put in the menu.
    menu=(),
)
