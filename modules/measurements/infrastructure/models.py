from __future__ import annotations

from django.db import models

from modules.core.infrastructure.models import TenantModel, TimeStampedModel, TranslatableModel


class Unit(TranslatableModel):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=60)
    si_base = models.CharField(max_length=20, blank=True)
    si_factor = models.FloatField(default=1.0)

    def __str__(self) -> str:
        return self.code


class Technique(TranslatableModel):
    code = models.SlugField(max_length=30, unique=True)
    name = models.CharField(max_length=80)
    module_code = models.SlugField(max_length=60)


class Magnitude(TranslatableModel):
    """`env_accel` is declared once but reported as Gs peak in one source and
    Gs peak-to-peak in another. That is why aggregation and unit travel with
    the reading and not with the catalogue entry."""

    code = models.SlugField(max_length=40, unique=True)
    technique = models.ForeignKey(Technique, on_delete=models.PROTECT, related_name="magnitudes")
    name = models.CharField(max_length=80)
    default_unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="+")
    default_aggregation = models.CharField(max_length=20, default="rms")
    higher_is_worse = models.BooleanField(default=True)
    decimals = models.PositiveSmallIntegerField(default=2)


class Instrument(TenantModel):
    code = models.SlugField(max_length=40)
    name = models.CharField(max_length=120, help_text="DSP Logger MX300 - SEMAPI, Microlog GX 75")
    manufacturer = models.CharField(max_length=80, blank=True)
    serial_number = models.CharField(max_length=60, blank=True)
    last_calibration = models.DateField(null=True, blank=True)
    next_calibration = models.DateField(null=True, blank=True)

    class Meta:
        unique_together = [("company", "code")]


class Reading(TenantModel):
    """Time series. Becomes a TimescaleDB hypertable on `taken_at`.

    `not_measured` rows are kept on purpose: "we could not measure" is data, and
    without it there is no plan-coverage KPI — 13% of the source RGP is exactly
    that case.
    """

    QUALITY = [("ok", "OK"), ("suspect", "Dudosa"), ("not_measured", "No medida")]
    NOT_MEASURED_REASONS = [
        ("equipment_off", "Equipo apagado"), ("no_access", "Sin acceso"),
        ("stopped", "Equipo parado"), ("retired", "Equipo retirado"),
    ]

    taken_at = models.DateTimeField(db_index=True)
    point = models.ForeignKey("assets.MeasurementPoint", on_delete=models.CASCADE, related_name="readings")
    service_visit = models.ForeignKey(
        "services.ServiceVisit", on_delete=models.SET_NULL, null=True, blank=True, related_name="readings"
    )
    magnitude = models.ForeignKey(Magnitude, on_delete=models.PROTECT, related_name="+")
    value = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="+")
    aggregation = models.CharField(max_length=20, default="rms")
    # Frozen with the threshold set that produced it: changing a standard must
    # not silently rewrite history.
    condition_status = models.ForeignKey(
        "thresholds.Status", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        limit_choices_to={"kind": "condition"},
    )
    threshold_set = models.ForeignKey(
        "thresholds.ThresholdSet", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    instrument = models.ForeignKey(Instrument, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    operator = models.ForeignKey("security.User", on_delete=models.SET_NULL, null=True, related_name="+")
    quality = models.CharField(max_length=20, choices=QUALITY, default="ok")
    not_measured_reason = models.CharField(max_length=30, choices=NOT_MEASURED_REASONS, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["company", "point", "magnitude", "-taken_at"]),
            models.Index(fields=["company", "-taken_at"]),
        ]


class ReadingBatch(TimeStampedModel):
    """Idempotency for field capture: the crew loses signal mid-upload and
    retries the whole equipment."""

    idempotency_key = models.CharField(max_length=64, unique=True)
    service_visit = models.ForeignKey("services.ServiceVisit", on_delete=models.CASCADE, related_name="batches")
    reading_count = models.PositiveIntegerField(default=0)
    # Which readings this batch produced. A count alone cannot answer a retry:
    # "the first N readings of the visit" are whatever was already there.
    reading_ids = models.JSONField(default=list, blank=True)


class Spectrum(TenantModel):
    """A spectrum, as both realities of doc 00 §8 have it.

    Today the instrument produces a screen capture and the analyst writes the
    diagnosis under it; tomorrow the same route exports arrays. Both live in
    one row so a machine's history does not split in two the day the CSV
    import lands: `image` is the capture, `data_key` the numeric pair.

    `caption` + `diagnosis` are the (image, label) pair the vision model will
    be trained on, which is why the diagnosis is a relation and not prose.
    """

    TYPES = [
        ("velocity", "Velocidad"), ("envelope", "Envolvente"),
        ("acceleration", "Aceleración"), ("demodulation", "Demodulación"),
        ("waveform", "Forma de onda"),
    ]

    point = models.ForeignKey(
        "assets.MeasurementPoint", on_delete=models.CASCADE, related_name="spectra"
    )
    reading = models.ForeignKey(
        Reading, on_delete=models.SET_NULL, null=True, blank=True, related_name="spectra"
    )
    service_visit = models.ForeignKey(
        "services.ServiceVisit", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="spectra",
    )
    taken_at = models.DateTimeField(db_index=True)
    spectrum_type = models.CharField(max_length=20, choices=TYPES, default="velocity")

    fmin_hz = models.FloatField(null=True, blank=True)
    fmax_hz = models.FloatField(null=True, blank=True)
    lines = models.PositiveIntegerField(null=True, blank=True)
    rpm_at_capture = models.FloatField(null=True, blank=True)
    window = models.CharField(max_length=20, blank=True)
    averages = models.PositiveSmallIntegerField(null=True, blank=True)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, null=True, blank=True, related_name="+")

    # The numeric pair, gzipped JSON in the object store. Kept out of the row
    # because a 3200-line spectrum is not something a list endpoint should
    # ever load, and out of the database because it is written once and read
    # whole.
    data_key = models.CharField(max_length=300, blank=True)
    peak_hz = models.FloatField(null=True, blank=True)
    peak_amplitude = models.FloatField(null=True, blank=True)

    # The capture of the instrument's screen, when that is all there is.
    image = models.ForeignKey(
        "media.MediaAsset", on_delete=models.SET_NULL, null=True, blank=True, related_name="spectra"
    )
    caption = models.CharField(max_length=300, blank=True)
    diagnosis = models.ManyToManyField("diagnostics.FaultMode", blank=True, related_name="spectra")

    class Meta:
        indexes = [
            models.Index(fields=["company", "point", "spectrum_type", "-taken_at"]),
        ]
        ordering = ["-taken_at"]

    @property
    def has_numeric_data(self) -> bool:
        return bool(self.data_key)
