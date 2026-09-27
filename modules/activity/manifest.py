from modules.core.domain.manifest import Manifest, MenuItem

MANIFEST = Manifest(
    code="activity",
    name="Registro de actividad",
    version="0.1.0",
    summary=(
        "Quién hizo qué y cuándo: inicios de sesión, clics, altas, cambios, bajas y "
        "subidas de archivos, en una tabla filtrable"
    ),
    category="Sistema",
    depends=("core", "security"),
    auto_install=True,
    permissions=(
        ("activity.view", "Ver el registro de actividad"),
        ("activity.export", "Exportar el registro de actividad"),
    ),
    menu=(
        MenuItem(
            label="Registro de actividad",
            route="/settings/activity",
            icon="activity",
            order=8,
            parent="settings",
            permission="activity.view",
        ),
    ),
    request_observer="modules.activity.infrastructure.observer.observe",
)
