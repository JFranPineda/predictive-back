from modules.core.domain.manifest import Manifest, MenuItem

MANIFEST = Manifest(
    code="blueprints",
    name="Planos de equipos",
    version="0.1.0",
    summary="Planos con puntos de rodamiento, eléctricos y de lubricación anotados encima",
    category="Activos",
    depends=('core', 'assets', 'media'),
    auto_install=True,
    permissions=(
        ("blueprints.view", "Ver planos"),
        ("blueprints.manage", "Editar planos y anotaciones"),
    ),
    menu=(
        MenuItem(label="Planos", route="/blueprints", icon="map", order=40, parent=None, permission='blueprints.view'),
    ),
)
