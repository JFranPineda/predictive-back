from __future__ import annotations

from django.db import models

from modules.core.infrastructure.models import TenantModel


class MediaAsset(TenantModel):
    KINDS = [
        ("photo", "Fotografía de servicio"),
        ("spectrum_image", "Captura de espectro"),
        ("thermogram", "Termograma"),
        ("ultrasound_capture", "Captura de ultrasonido"),
        ("blueprint", "Plano"),
        ("nameplate", "Placa de características"),
        ("document", "Documento"),
        ("report_pdf", "Reporte PDF"),
    ]
    STATES = [
        ("pending", "Pendiente"), ("uploading", "Subiendo"), ("processing", "Procesando"),
        ("done", "Listo"), ("failed", "Fallido"),
    ]

    kind = models.CharField(max_length=30, choices=KINDS, db_index=True)
    # Generic owner: a photo belongs to a visit, a point, a finding or a spectrum.
    owner_type = models.CharField(max_length=40, db_index=True)
    owner_id = models.PositiveBigIntegerField(db_index=True)

    original_key = models.CharField(max_length=300)
    original_format = models.CharField(max_length=20)
    original_bytes = models.PositiveBigIntegerField(default=0)
    checksum_sha256 = models.CharField(max_length=64, db_index=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)

    captured_at = models.DateTimeField(null=True, blank=True)
    camera_model = models.CharField(max_length=120, blank=True)
    exif = models.JSONField(default=dict, blank=True)
    geo = models.JSONField(null=True, blank=True)

    # Denormalised so the equipment gallery is one indexed range scan instead
    # of a join through visits. Plain ids, not FKs: `media` depends on `core`
    # alone, and the owner has always been generic. They are filled on upload
    # from the visit and never change afterwards.
    equipment_ref = models.PositiveBigIntegerField(null=True, blank=True)
    captured_on = models.DateField(null=True, blank=True)

    processing_state = models.CharField(max_length=20, choices=STATES, default="pending", db_index=True)
    derivatives = models.JSONField(default=dict, blank=True)
    thermal_meta = models.JSONField(null=True, blank=True)
    caption = models.CharField(max_length=300, blank=True)
    uploaded_by = models.ForeignKey("security.User", on_delete=models.SET_NULL, null=True, related_name="+")

    class Meta:
        unique_together = [("company", "checksum_sha256")]
        indexes = [
            models.Index(fields=["company", "owner_type", "owner_id"]),
            models.Index(fields=["processing_state", "created_at"]),
            # The gallery pages by (created_at, id) descending and filters by
            # kind, so the index carries the sort: thousands of images per
            # machine cost the same as a dozen.
            models.Index(
                fields=["company", "equipment_ref", "kind", "-created_at", "-id"],
                name="media_equipment_page_idx",
            ),
            models.Index(
                fields=["company", "equipment_ref", "-created_at", "-id"],
                name="media_equipment_all_idx",
            ),
        ]
