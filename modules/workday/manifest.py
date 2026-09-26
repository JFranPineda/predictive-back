from modules.core.domain.manifest import Manifest, MenuItem

MANIFEST = Manifest(
    code="workday",
    name="Jornada, ATS y cierre del día",
    version="0.1.0",
    summary=(
        "El ingeniero jefe abre y cierra la jornada con su clave; sin ATS no se fotografía "
        "un conjunto, y cerrado el día los técnicos ya no modifican nada"
    ),
    category="Operación",
    depends=("core", "assets", "services", "security", "media"),
    permissions=(
        ("workday.view", "Ver jornadas y trabajos del día"),
        ("workday.manage", "Abrir, cerrar y reabrir la jornada (ingeniero jefe)"),
        ("workday.register_permit", "Registrar ATS y observaciones de campo"),
        ("workday.view_permits", "Ver los ATS de la jornada"),
    ),
    menu=(
        MenuItem(label="Jornada", route="/workday", icon="calendar-clock",
                 order=12, parent=None, permission="workday.view"),
    ),
    on_install="modules.workday.infrastructure.setup.install",
    write_guard="modules.workday.infrastructure.guard.guard",
)
