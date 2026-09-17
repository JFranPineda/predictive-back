from modules.core.domain.manifest import Manifest, MenuItem

MANIFEST = Manifest(
    code="operating_data",
    name="Datos operativos",
    version="0.1.0",
    summary="Parámetros del equipo en operación: rpm, presiones, corriente, horas, lubricación y alineamiento",
    category="Análisis predictivo",
    depends=('core', 'assets', 'measurements', 'services'),
    auto_install=True,
    permissions=(
        ("operating_data.view", "Ver datos operativos"),
        ("operating_data.add", "Registrar datos operativos"),
    ),
    menu=(
        MenuItem(label="Datos operativos", route="/operating", icon="sliders", order=50, parent=None, permission='operating_data.view'),
    ),
)
