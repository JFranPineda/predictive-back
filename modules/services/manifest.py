from modules.core.domain.manifest import Manifest, MenuItem

MANIFEST = Manifest(
    code="services",
    name="Servicios y programación",
    version="0.1.0",
    summary="Planes anuales, órdenes de servicio, visitas por equipo, ejecutantes y cumplimiento",
    category="Operación",
    depends=("core", "assets", "security"),
    auto_install=True,
    permissions=(
        ("services.view", "Ver servicios"),
        ("services.manage_plan", "Gestionar planes"),
        ("services.manage_order", "Gestionar órdenes de servicio"),
        ("services.close_visit", "Cerrar visitas de cualquier ejecutante"),
        ("services.view_authorship", "Ver quién ejecutó cada servicio"),
    ),
    menu=(
        MenuItem(label="Servicios", route="/services", icon="calendar", order=25,
                 permission="services.view"),
        MenuItem(label="Ejecución", route="/services/authorship", icon="user-check", order=26,
                 permission="services.view_authorship"),
    ),
    events_published=("ServiceCompleted",),
)
