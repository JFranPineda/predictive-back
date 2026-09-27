from modules.core.domain.manifest import Manifest, MenuItem

MANIFEST = Manifest(
    code="workday",
    name="Jornada, ATS y cierre del día",
    version="0.2.0",
    summary=(
        "El ingeniero jefe abre y cierra la jornada con su clave; cada servicio lleva su ATS, "
        "tres firmas de inicio sin las que no se llena nada del conjunto y un cierre firmado "
        "que fija su hora final; cerrado el día los técnicos ya no modifican nada"
    ),
    category="Operación",
    depends=("core", "assets", "services", "security", "media"),
    permissions=(
        ("workday.view", "Ver jornadas y trabajos del día"),
        ("workday.manage", "Abrir y cerrar la jornada (ingeniero jefe)"),
        ("workday.reopen", "Reabrir una jornada cerrada (ingeniero jefe y administradores)"),
        ("workday.register_permit", "Registrar servicios, su ATS, firmas y observaciones de campo"),
        ("workday.view_permits", "Ver los servicios y ATS de la jornada"),
        ("workday.close_service", "Cerrar un servicio con clave: fija su hora final (ingeniero jefe)"),
        ("workday.unlock_service", "Desbloquear un servicio sin sus firmas de inicio (administrador)"),
    ),
    menu=(
        MenuItem(label="Jornada", route="/workday", icon="calendar-clock",
                 order=12, parent=None, permission="workday.view"),
    ),
    on_install="modules.workday.infrastructure.setup.install",
    write_guard="modules.workday.infrastructure.guard.guard",
)
