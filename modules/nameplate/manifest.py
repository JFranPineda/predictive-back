from modules.core.domain.manifest import Manifest

MANIFEST = Manifest(
    code="nameplate",
    name="Datos de fábrica",
    version="0.1.0",
    summary="Datos nominales del fabricante, rodamientos con geometría y lubricantes",
    category="Activos",
    depends=('core', 'assets'),
    auto_install=True,
    permissions=(
        ("nameplate.view", "Ver datos de placa"),
        ("nameplate.manage", "Editar datos de placa"),
    ),
)
