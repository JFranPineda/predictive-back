"""Fills the services the demo never had, on top of what `seed_demo` left.

`seed_demo` builds the plant and one year of vibration and thermography. Every
other screen then looks broken for a reason that is not a bug: the ultrasound
round has no readings, the oil analysis has no limits, and the galleries are
empty because nobody ever uploaded a photograph.

This command adds those, and only those. It is additive and idempotent: run it
twice and the second run reports zeros. Nothing here rewrites what the real
RGP produced — the vibration history stays exactly as it was imported.

    manage.py tenants run ambev seed_more
    manage.py tenants run ambev seed_more --images 0     # only the readings
"""

from __future__ import annotations

import io
import math
import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from modules.assets.models import Equipment, MeasurementPoint
from modules.core.models import Company
from modules.diagnostics.models import FaultMode
from modules.measurements.models import (
    Instrument,
    Magnitude,
    Reading,
    Spectrum,
    Technique,
    Unit,
)
from modules.media.models import MediaAsset
from modules.security.models import User
from modules.services.models import ServiceOrder, ServiceVisit, VisitParticipant
from modules.thresholds.models import Status, ThresholdBand, ThresholdSet

# What each round measures, and the band a healthy machine sits in. The
# ultrasound figures are the dB levels the source route reports on bearings;
# the oil ones are what a 40 °C viscosity report looks like for an ISO VG 68.
ROUNDS = {
    "ultrasound": {
        "prefix": "MPd-US",
        "instrument": "skf_gx75",
        # Airborne dB finds the friction; conventional UT measures what is
        # left of the metal. The report in `docs/v2` is the second kind: a
        # thickness sweep over the journals of the dryer rolls.
        "magnitudes": {"us_db": (12.0, 4.0), "thickness_mm": (9.6, 1.4)},
        "equipment_types": ("motor", "pump", "gearbox", "fan", "blower", "compressor"),
        "share": 0.45,
    },
    "oil_analysis": {
        "prefix": "MPd-AC",
        "instrument": "semapi_mx300",
        "magnitudes": {"viscosity_40": (68.0, 6.0), "water_ppm": (120.0, 60.0)},
        "equipment_types": ("gearbox", "compressor", "blower"),
        "share": 1.0,
    },
    "insulating_oil": {
        "prefix": "MPd-AD",
        "instrument": "semapi_mx300",
        "magnitudes": {"dielectric_kv": (52.0, 8.0)},
        "equipment_types": ("other",),
        "share": 0.25,
    },
}

# Limits the demo was missing. Both magnitudes get worse as the number falls,
# which is the case `higher_is_worse=False` exists for.
MISSING_LIMITS = {
    # Derived from the verdicts in `ORDEN_14778`: every polín the inspector
    # marked MEDIO has a reading under 8.0 mm, and every ACEPTABLE one sits
    # at or above it. The wall only ever gets thinner, so lower is worse.
    "thickness_mm": {"unit": "mm", "aggregation": "min",
                     "bands": [("operational", 8.0, None), ("alarm", 7.0, 8.0),
                               ("shutdown", None, 7.0)]},
    "viscosity_40": {"unit": "cSt", "aggregation": "avg",
                     "bands": [("operational", 61.0, None), ("alarm", 54.0, 61.0),
                               ("shutdown", None, 54.0)]},
    "dielectric_kv": {"unit": "kV", "aggregation": "avg",
                      "bands": [("operational", 45.0, None), ("alarm", 30.0, 45.0),
                                ("shutdown", None, 30.0)]},
}

CAPTIONS = {
    "spectrum_image": [
        "En modo Velocidad, 1X dominante: desalineamiento paralelo",
        "Envolvente con armónicas de BPFO: desgaste de pista externa",
        "2X y 3X con soltura mecánica en el apoyo",
        "Espectro dentro de norma, sin componentes de falla",
    ],
    "thermogram": [
        "ΔT de 14 °C contra el componente similar de igual carga",
        "Bornera con calentamiento localizado, revisar ajuste",
        "Distribución uniforme, sin puntos calientes",
    ],
    "ultrasound_capture": [
        "Nivel estable, sin fricción audible",
        "Incremento de 8 dB respecto a la ronda anterior",
    ],
    "photo": [
        "Vista general del conjunto en operación",
        "Acople y guarda de seguridad",
        "Base y pernos de anclaje",
        "Placa de características del motor",
    ],
}


class Command(BaseCommand):
    help = "Adds the services, media and spectra the demo was missing"

    def add_arguments(self, parser) -> None:
        parser.add_argument("--rounds", type=int, default=4)
        parser.add_argument("--images", type=int, default=3, help="Per visit, at most")
        parser.add_argument("--machines", type=int, default=260)
        parser.add_argument("--visits", type=int, default=3)
        parser.add_argument("--spectra", type=int, default=400)
        parser.add_argument("--seed", type=int, default=20260918)

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        random.seed(options["seed"])
        company = Company.objects.first()
        if company is None:
            self.stderr.write("No hay empresa: ejecuta primero seed_demo")
            return

        limits = self._limits(company)
        services = self._services(company, options["rounds"])
        # A magnitude added after its round already exists would otherwise
        # never get a reading, and a magnitude with no readings is invisible.
        services += self._top_up(company)
        images = self._media(
            company, options["images"], options["machines"], options["visits"]
        )
        spectra = self._spectra(company, options["spectra"])

        self.stdout.write(
            f"limites nuevos {limits} · lecturas nuevas {services} · "
            f"imagenes {images} · espectros {spectra}"
        )

    # ------------------------------------------------------------------ limits

    def _limits(self, company) -> int:
        """A reading with no band is never graded, and never reaches a summary."""

        self._thickness_magnitude()

        statuses = {row.code: row for row in Status.objects.filter(company=company, kind="condition")}
        made = 0
        for magnitude_code, spec in MISSING_LIMITS.items():
            if ThresholdSet.objects.filter(company=company, magnitude_code=magnitude_code).exists():
                continue
            threshold_set = ThresholdSet.objects.create(
                company=company, scope="global", scope_ref_id=None,
                magnitude_code=magnitude_code, unit_code=spec["unit"],
                aggregation=spec["aggregation"], valid_from=date(2026, 1, 1),
                rationale="Criterio de planta: el valor empeora al bajar",
            )
            ThresholdBand.objects.bulk_create([
                ThresholdBand(
                    threshold_set=threshold_set, status=statuses[code], order=order,
                    min_value=None if low is None else Decimal(str(low)),
                    max_value=None if high is None else Decimal(str(high)),
                )
                for order, (code, low, high) in enumerate(spec["bands"])
            ])
            made += 1
        return made

    @staticmethod
    def _thickness_magnitude() -> None:
        """Conventional UT: what is left of the wall, in millimetres."""

        unit, _ = Unit.objects.get_or_create(
            code="mm", defaults={"name": "Milímetros", "translations": {"name": {"es": "Milímetros"}}}
        )
        # Its own service: a contact-probe thickness sweep is a non-destructive
        # test in millimetres, not a reading of the dB ultrasound round.
        technique = Technique.objects.filter(code="ndt_thickness").first()
        if technique is None:
            return
        Magnitude.objects.update_or_create(
            code="thickness_mm",
            defaults={
                "technique": technique,
                "name": "Espesor de pared",
                "default_unit": unit,
                "default_aggregation": "min",
                # A wall only gets thinner: the minimum is the verdict.
                "higher_is_worse": False,
                "decimals": 2,
                "per_axis": False,
                "short_code": "ESP {n}",
                "translations": {"name": {"es": "Espesor de pared", "en": "Wall thickness"}},
            },
        )

    # ---------------------------------------------------------------- services

    def _services(self, company, rounds: int) -> int:
        plant = Equipment.objects.select_related(
            "asset_group__sector__area__plant"
        ).first().asset_group.sector.area.plant
        crew = list(User.objects.filter(memberships__company=company).distinct()[:4]) or list(
            User.objects.all()[:4]
        )
        instruments = {row.code: row for row in Instrument.objects.filter(company=company)}
        statuses = {row.code: row for row in Status.objects.filter(company=company, kind="condition")}
        made = 0

        for technique_code, spec in ROUNDS.items():
            technique = Technique.objects.filter(code=technique_code).first()
            if technique is None:
                continue
            magnitudes = {
                code: Magnitude.objects.filter(code=code).select_related("default_unit").first()
                for code in spec["magnitudes"]
            }
            if not all(magnitudes.values()):
                continue
            if ServiceOrder.objects.filter(company=company, technique=technique).exists():
                continue

            fleet = list(
                Equipment.objects.filter(
                    company=company, equipment_type__in=spec["equipment_types"]
                ).order_by("id")
            )
            fleet = fleet[: max(int(len(fleet) * spec["share"]), 1)]
            if not fleet:
                continue

            made += self._round_for(
                company, plant, technique, spec, fleet, crew, instruments,
                magnitudes, statuses, rounds,
            )
        return made

    def _round_for(self, company, plant, technique, spec, fleet, crew, instruments,
                   magnitudes, statuses, rounds) -> int:
        now = timezone.now()
        orders = []
        for index in range(rounds):
            when = now - timedelta(days=60 * (rounds - index - 1))
            orders.append((
                ServiceOrder.objects.create(
                    company=company, plant=plant, technique=technique,
                    code=f"{spec['prefix']}-N°{index + 1:03d}-26",
                    client_work_order=f"OT-{1390000 + index}",
                    scheduled_from=when.date(), scheduled_to=when.date() + timedelta(days=2),
                    status="done" if index < rounds - 1 else "in_progress",
                    lead_analyst=crew[index % len(crew)],
                    supervisor=crew[-1],
                ),
                when,
            ))

        points = {}
        for point in MeasurementPoint.objects.filter(equipment__in=fleet):
            points.setdefault(point.equipment_id, []).append(point)

        visits, readings, participants = [], [], []
        for item in fleet:
            # Each machine drifts on its own line, so the trend is a trend and
            # not noise around a constant.
            drift = random.uniform(-0.35, 0.9)
            for index, (order, when) in enumerate(orders):
                visit = ServiceVisit.objects.create(
                    company=company, service_order=order, equipment=item,
                    visited_at=when - timedelta(hours=item.id % 7),
                    availability_status=item.availability_status,
                    instrument=instruments.get(spec["instrument"]),
                    duration_min=random.randint(6, 20),
                    is_closed=index < len(orders) - 1,
                )
                visits.append(visit)
                lead = random.choice(crew)
                participants.append(VisitParticipant(visit=visit, user=lead, role="lead_analyst"))

                target = points.get(item.id, [])[:1]
                for point in target:
                    for code, (centre, spread) in spec["magnitudes"].items():
                        magnitude = magnitudes[code]
                        value = _drifted(centre, spread, drift, index, len(orders))
                        readings.append(Reading(
                            company=company, taken_at=visit.visited_at, point=point,
                            service_visit=visit, magnitude=magnitude,
                            value=Decimal(f"{value:.2f}"), unit=magnitude.default_unit,
                            aggregation=magnitude.default_aggregation,
                            condition_status=_grade(value, magnitude, statuses),
                            operator=lead, instrument=visit.instrument, quality="ok",
                        ))
        VisitParticipant.objects.bulk_create(participants, batch_size=500)
        Reading.objects.bulk_create(readings, batch_size=2000)
        return len(readings)

    def _top_up(self, company) -> int:
        """Fills a magnitude the round was missing, on the visits it already has."""

        statuses = {row.code: row for row in Status.objects.filter(company=company, kind="condition")}
        made = 0
        for technique_code, spec in ROUNDS.items():
            for code, (centre, spread) in spec["magnitudes"].items():
                magnitude = Magnitude.objects.filter(code=code).select_related(
                    "default_unit"
                ).first()
                if magnitude is None or Reading.objects.filter(magnitude=magnitude).exists():
                    continue
                visits = list(
                    ServiceVisit.objects.filter(
                        company=company, service_order__technique__code=technique_code
                    ).select_related("equipment")
                )
                rows = []
                for visit in visits:
                    point = MeasurementPoint.objects.filter(equipment=visit.equipment).first()
                    if point is None:
                        continue
                    value = _drifted(centre, spread, random.uniform(-1, 1), 1, 2)
                    rows.append(Reading(
                        company=company, taken_at=visit.visited_at, point=point,
                        service_visit=visit, magnitude=magnitude,
                        value=Decimal(f"{value:.2f}"), unit=magnitude.default_unit,
                        aggregation=magnitude.default_aggregation,
                        condition_status=_grade(value, magnitude, statuses),
                        instrument=visit.instrument, quality="ok",
                    ))
                Reading.objects.bulk_create(rows, batch_size=1000)
                made += len(rows)
        return made

    # ------------------------------------------------------------------- media

    def _media(self, company, per_visit: int, machines: int, visits_each: int) -> int:
        """Photographs and captures, so the galleries stop being empty.

        The images are drawn, not photographed — there is no real photo set in
        the repository — but everything around them is real: they hang off the
        visit that produced them, carry the kind their service captures, and
        the caption says what the analyst would have written.
        """
        if per_visit <= 0:
            return 0
        from modules.media.domain.derivatives import Variant, storage_key
        from modules.media.infrastructure.local_store import checksum, store

        backend = store()
        kind_of = {
            "vibration": "spectrum_image", "thermography": "thermogram",
            "ultrasound": "ultrasound_capture", "oil_analysis": "document",
            "insulating_oil": "document",
        }
        # Spread across machines, not across dates. Taking the newest visits
        # piles every image onto the handful of machines that were visited
        # last, and the gallery of every other one stays empty.
        visits = []
        for equipment_id in Equipment.objects.filter(company=company).values_list(
            "id", flat=True
        )[:machines]:
            visits += list(
                ServiceVisit.objects.filter(company=company, equipment_id=equipment_id)
                .select_related("service_order__technique", "equipment")
                .order_by("-visited_at")[:visits_each]
            )
        made = 0
        for visit in visits:
            if MediaAsset.objects.filter(owner_type="visit", owner_id=visit.id).exists():
                continue
            technique = visit.service_order.technique.code
            kinds = ["photo"] + [kind_of.get(technique, "photo")] * (per_visit - 1)
            for slot, kind in enumerate(kinds[:per_visit]):
                payload = _draw(visit, kind, slot)
                digest = checksum(payload)
                if MediaAsset.objects.filter(company=company, checksum_sha256=digest).exists():
                    continue
                key = storage_key(company.id, digest, None, "jpg")
                backend.put(key, payload, content_type="image/jpeg")
                asset = MediaAsset.objects.create(
                    company=company, kind=kind, owner_type="visit", owner_id=visit.id,
                    equipment_ref=visit.equipment_id, captured_on=visit.visited_at.date(),
                    original_key=key, original_format="jpeg", original_bytes=len(payload),
                    checksum_sha256=digest,
                    caption=random.choice(CAPTIONS.get(kind, CAPTIONS["photo"])),
                    processing_state="pending",
                )
                _thumbnail(asset, payload, backend, storage_key, Variant)
                made += 1
        return made

    # ----------------------------------------------------------------- spectra

    def _spectra(self, company, total: int) -> int:
        """Numeric spectra, with the shape a real machine produces.

        A synthetic 1X plus its harmonics and a bearing family is not the same
        as random noise: it is what makes the peak, the span and the diagnosis
        agree with each other on screen.
        """
        import gzip
        import json

        from modules.media.infrastructure.local_store import checksum, store

        if total <= 0:
            return 0
        backend = store()
        faults = list(FaultMode.objects.all()[:12])
        unit = Unit.objects.filter(code="mm/s").first()
        captures = list(
            MediaAsset.objects.filter(company=company, kind="spectrum_image")
            .order_by("-created_at")[:total]
        )
        made = 0
        for capture in captures:
            if Spectrum.objects.filter(image=capture).exists():
                continue
            point = MeasurementPoint.objects.filter(equipment_id=capture.equipment_ref).first()
            if point is None:
                continue
            rpm = random.choice([1480, 1770, 2950, 3560])
            curve = _synthetic_curve(rpm)
            body = gzip.compress(json.dumps(curve).encode())
            digest = checksum(body)
            key = f"spectra/{company.id}/{digest[:2]}/{digest}.json.gz"
            backend.put(key, body, content_type="application/gzip")

            peak_index = max(range(len(curve["amp"])), key=curve["amp"].__getitem__)
            spectrum = Spectrum.objects.create(
                company=company, point=point, taken_at=capture.created_at,
                service_visit_id=capture.owner_id if capture.owner_type == "visit" else None,
                spectrum_type="velocity", unit=unit,
                fmin_hz=curve["freq"][0], fmax_hz=curve["freq"][-1], lines=len(curve["freq"]),
                rpm_at_capture=rpm, window="hanning", averages=8,
                data_key=key, peak_hz=curve["freq"][peak_index],
                peak_amplitude=curve["amp"][peak_index],
                image=capture, caption=capture.caption,
            )
            if faults and random.random() < 0.6:
                spectrum.diagnosis.set(random.sample(faults, k=random.randint(1, 2)))
            made += 1
        return made


# --------------------------------------------------------------------- helpers


def _drifted(centre: float, spread: float, drift: float, index: int, total: int) -> float:
    progress = index / max(total - 1, 1)
    return max(centre + spread * drift * progress + random.uniform(-0.25, 0.25) * spread, 0.1)


def _grade(value: float, magnitude, statuses: dict):
    """Grades against the same bands the API resolves, direction included."""

    spec = MISSING_LIMITS.get(magnitude.code)
    if spec is None:
        # Higher is worse: the usual case, two thirds and one third of the way.
        centre = {"us_db": (20.0, 28.0), "water_ppm": (200.0, 300.0)}.get(magnitude.code)
        if centre is None:
            return statuses.get("operational")
        alarm, shutdown = centre
        if value >= shutdown:
            return statuses.get("shutdown")
        return statuses.get("alarm") if value >= alarm else statuses.get("operational")

    for code, low, high in spec["bands"]:
        if (low is None or value >= low) and (high is None or value < high):
            return statuses.get(code)
    return statuses.get("operational")


def _synthetic_curve(rpm: int) -> dict:
    """1X with harmonics, a bearing family and a noise floor."""

    turning = rpm / 60.0
    bearing = turning * 3.58
    frequencies, amplitudes = [], []
    for line in range(1600):
        hz = line * 0.5
        value = 0.02 + random.uniform(0, 0.015)
        for order, weight in ((1, 1.8), (2, 0.9), (3, 0.35)):
            value += weight * math.exp(-(((hz - turning * order) / 1.2) ** 2))
        for order in (1, 2, 3):
            value += 0.28 * math.exp(-(((hz - bearing * order) / 1.6) ** 2))
        frequencies.append(round(hz, 2))
        amplitudes.append(round(value, 4))
    return {"freq": frequencies, "amp": amplitudes, "unit": "mm/s"}


def _draw(visit, kind: str, slot: int) -> bytes:
    """A readable stand-in: what it is, of what machine, on what date."""

    from PIL import Image, ImageDraw

    palette = {
        "photo": ((38, 50, 64), (226, 232, 240)),
        "spectrum_image": ((12, 20, 34), (125, 211, 252)),
        "thermogram": ((30, 12, 44), (251, 146, 60)),
        "ultrasound_capture": ((10, 32, 28), (134, 239, 172)),
        "document": ((244, 244, 245), (24, 24, 27)),
    }
    background, ink = palette.get(kind, palette["photo"])
    image = Image.new("RGB", (960, 720), background)
    draw = ImageDraw.Draw(image)

    if kind == "spectrum_image":
        for x in range(0, 960, 6):
            height = int(abs(math.sin(x / 37.0 + slot)) * 260 + random.randint(0, 40))
            draw.line([(x, 660), (x, 660 - height)], fill=ink)
    elif kind == "thermogram":
        for radius in range(260, 0, -12):
            shade = (255, max(40, 240 - radius), 40)
            draw.ellipse(
                [480 - radius, 360 - radius // 2, 480 + radius, 360 + radius // 2], fill=shade
            )
    elif kind == "ultrasound_capture":
        middle = 400
        for x in range(0, 960, 3):
            span = int(abs(math.sin(x / 21.0)) * (60 + slot * 12))
            draw.line([(x, middle - span), (x, middle + span)], fill=ink)
    else:
        draw.rectangle([60, 120, 900, 600], outline=ink, width=4)
        draw.line([60, 120, 900, 600], fill=ink, width=2)

    # The TAG has to be on the image. Half the plant is called "MOTOR" and the
    # round stamps the same code and date on all of them, so without it every
    # photograph of a round is byte-identical and the content-addressed store
    # collapses them into one.
    machine = visit.equipment
    draw.text((40, 30), f"{machine.name[:40]} · {machine.client_tag or machine.asset_code}", fill=ink)
    draw.text((40, 50), f"{visit.service_order.code} · {visit.visited_at:%Y-%m-%d %H:%M}", fill=ink)
    draw.text((40, 680), f"{kind} · visita {visit.id}", fill=ink)

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=82)
    return buffer.getvalue()


def _thumbnail(asset, payload: bytes, backend, storage_key, Variant) -> None:
    from PIL import Image

    image = Image.open(io.BytesIO(payload))
    asset.width, asset.height = image.size
    image.thumbnail((320, 320))
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=72)
    key = storage_key(asset.company_id, asset.checksum_sha256, Variant.THUMB, "jpg")
    backend.put(key, buffer.getvalue(), content_type="image/jpeg")
    asset.derivatives = {"thumb": {"key": key, "w": image.width, "h": image.height}}
    asset.save(update_fields=["derivatives", "width", "height", "updated_at"])
