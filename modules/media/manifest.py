from modules.core.domain.manifest import Manifest

MANIFEST = Manifest(
    code="media",
    name="Multimedia",
    version="0.1.0",
    summary="Ingesta masiva de imágenes, conversión nocturna y galerías por equipo",
    category="Sistema",
    depends=("core",),
    auto_install=True,
    permissions=(
        ("media.view", "Ver multimedia"),
        ("media.upload", "Subir multimedia"),
        ("media.delete", "Eliminar multimedia"),
        ("media.download_original", "Descargar el original sin comprimir"),
    ),
    events_subscribed=("MediaUploaded",),
    events_published=("MediaUploaded",),
)
