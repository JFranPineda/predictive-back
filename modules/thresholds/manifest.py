from modules.core.domain.manifest import Manifest, MenuItem

MANIFEST = Manifest(
    code="thresholds",
    name="Umbrales, estados y normas",
    version="0.2.0",
    summary="Normas ISO, bandas por norma y clase de máquina, y estados por técnica",
    category="Configuración",
    depends=("core", "assets"),
    auto_install=True,
    permissions=(
        ("thresholds.view_set", "Ver umbrales"),
        ("thresholds.manage_set", "Crear y editar umbrales"),
        ("thresholds.manage_status", "Gestionar estados y su color"),
        ("thresholds.manage_standard", "Gestionar normas ISO"),
        ("thresholds.manage_profile", "Configurar los estados de cada técnica"),
        ("thresholds.recalculate", "Recalcular estados históricos"),
    ),
    menu=(
        MenuItem(label="Medidas", route="/settings/magnitudes", icon="ruler",
                 order=16, parent="settings", permission="thresholds.view_set"),
        MenuItem(label="Normas", route="/settings/standards", icon="book",
                 order=18, parent="settings", permission="thresholds.manage_standard"),
        MenuItem(label="Umbrales", route="/settings/thresholds", icon="gauge",
                 order=20, parent="settings", permission="thresholds.view_set"),
        MenuItem(label="Estados", route="/settings/statuses", icon="palette",
                 order=22, parent="settings", permission="thresholds.manage_status"),
    ),
    fixtures=("statuses.yaml", "technique_profiles.yaml", "standards.yaml", "iso_10816_3.yaml",
              "technical_associates.yaml"),
    events_subscribed=("ReadingRecorded",),
    events_published=("ThresholdSetChanged", "StandardChanged", "EquipmentStatusChanged"),
)
