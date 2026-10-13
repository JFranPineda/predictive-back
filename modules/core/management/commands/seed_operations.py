"""Fills what a running plant fills by itself after a round: the diagnoses,
the corrective work, the alignments, the END round on the boilers and the UT
round on the malt conveyors' idlers.

It builds on what the plant already says. The September vibration round
(MPd-AV-N°006-26) carries the analyst's own diagnoses with their
recommendations open — «Alinear con sistema láser el Motor Vs. Bomba»,
«balancear el ventilador»… This command writes the July round's findings that
led to them, then executes them: the maintenance records, the laser
alignments with their before and after, and marks each recommendation done
or scheduled. Every date hangs off that September round, so the story reads in
order whenever the command runs.

Everything goes in through the API, signed in as an administrator, so it
obeys the same rules as typed data: the alignment scale is frozen per record,
every thickness is graded by the cascade, new machines count against the
licence. Authorship is then put back on the people who would have done the
work, since the API records whoever is signed in.

Additive and idempotent: each part is skipped when it is already there.

    manage.py tenants run ambev seed_operations
"""

from __future__ import annotations

import io
import random
from datetime import date, datetime, time, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from modules.assets.models import AssetGroup, Equipment, MeasurementPoint, Sector
from modules.diagnostics.models import EquipmentLogEntry
from modules.licensing.infrastructure.context import current_alias, current_tenant
from modules.measurements.models import Reading
from modules.security.models import User
from modules.services.models import ServiceOrder, ServiceVisit, VisitParticipant

SEPTEMBER = "MPd-AV-N°006-26"
JULY = "MPd-AV-N°004-26"
JUNE = "MPd-AV-N°003-26"
ALIGNMENT_ORDER = "MPd-AL-N°001-26"
THICKNESS_ORDER = "END-ES-N°001-26"
ROLLERS_ORDER = "END-UR-N°001-26"

PEOPLE = {
    "admin": "admin@simiai.pe",
    "analyst": "carlos.balta@simiai.pe",
    "inspector": "henry.tejada@contratista.pe",
    "aligner": "walter.g@contratista.pe",
    "technician": "jorge.a@simiai.pe",
}

# What the July round saw on the machines September diagnosed: the start of
# the same fault, still in alarm. Keyed by the TAG that carries the September
# diagnosis.
JULY_FINDINGS = {
    "B131007A": (["misalignment_parallel"],
                 "1X y 2X crecientes en radial del lado acople: inicio de desalineamiento entre motor y "
                 "bomba."),
    "B131007B": (["bearing_wear", "soft_foot"],
                 "Frecuencias de rodamiento en la envolvente de la bomba y vibración sensible al ajuste de "
                 "pernos: desgaste inicial de rodamientos con indicio de pata coja."),
    "MB131010A": (["misalignment_parallel", "bearing_wear"],
                  "1X y 2X dominantes en el motor y picos de rodamiento en la envolvente: desalineamiento "
                  "con desgaste inicial de rodamientos."),
    "B131013A": (["misalignment_parallel"],
                 "2X en axial por encima de la mitad de 1X en la bomba: desalineamiento entre motor y "
                 "bomba."),
    "C141002": (["misalignment_angular"],
                "Vibración axial elevada con 1X dominante en el compresor: desalineamiento angular "
                "motor-compresor."),
    "C151001": (["misalignment_parallel"],
                "1X radial dominante en el lado acople del compresor: desalineamiento motor-compresor."),
    "MB501003": (["unbalance"],
                 "1X radial dominante y estable en fase en el motor: desbalance, probablemente por suciedad "
                 "o erosión del impulsor."),
    "MB501014": (["unbalance", "induced_stress"],
                 "1X radial dominante que cambia con el caudal: desbalance asociado a tensión de tuberías."),
    "MSP561003": (["unbalance"], "1X radial dominante en el ventilador del motor: desbalance dinámico."),
    "MB562002": (["mechanical_looseness", "unbalance"],
                 "Armónicos de 1X con la base levantada: soltura mecánica y desbalance del impulsor."),
    "MR562023": (["bearing_wear"],
                 "Picos de frecuencias de rodamiento en la envolvente del motor: desgaste de rodamientos en "
                 "etapa inicial."),
    "SP562004": (["unbalance"], "1X radial dominante en el impelente del soplador: desbalance dinámico."),
    "MSP562S001": (["unbalance"],
                   "1X radial muy por encima del resto del espectro en el ventilador principal: desbalance "
                   "dinámico."),
    "MC561S001": (["misalignment_parallel", "belt_pulley"],
                  "1X y 2X con la frecuencia de faja marcada: desalineamiento de poleas y fajas gastadas."),
}
JULY_RECOMMENDATION = (
    "Mantener el monitoreo mensual y programar la corrección en la próxima parada de la línea."
)

# The laser alignments: (key, TAG of the train's driver, days after the
# September round, rpm, aligner, before, after, in the alignment order?,
# note). Values are angular H, parallel H, angular V, parallel V — angular in
# mm/100 mm, parallel in mm.
ALIGNMENTS = [
    ("caldera3_br1", "MB131013A", 4, 3560, "skf", (0.11, 0.21, 0.09, 0.16), (0.02, 0.03, 0.01, 0.02),
     False, "Pata coja corregida antes de alinear (0.12 → 0.03 mm)."),
    ("caldera2_br1", "MB131010A", 10, 3560, "skf", (0.08, 0.14, 0.06, 0.12), (0.02, 0.02, 0.03, 0.01),
     False, "Holgura del acople dentro de tolerancia."),
    ("caldera1_br2", "MB131007B", 16, 3560, "skf", (0.07, 0.12, 0.05, 0.09), (0.01, 0.02, 0.02, 0.03),
     True, "Alineado al cierre del cambio de rodamientos de la bomba."),
    ("caldera1_br1", "MB131007A", 17, 3560, "skf", (0.13, 0.19, 0.10, 0.17), (0.02, 0.03, 0.02, 0.02),
     True, "Pernos de anclaje reemplazados antes de alinear."),
    ("caldera2_br2", "MB131010B", 17, 3560, "skf", (0.03, 0.04, 0.02, 0.03), (0.03, 0.04, 0.02, 0.03),
     True, "Verificación preventiva: dentro de tolerancia, no requirió corrección."),
    ("co2_n1", "C151001", 18, 1780, "skf", (0.09, 0.15, 0.07, 0.11), (0.03, 0.04, 0.02, 0.03),
     True, "Poleas de transmisión sin desgaste en canales."),
    ("sabroe_n2", "MC141002", 18, 3560, "skf", (0.06, 0.11, 0.08, 0.10), (0.02, 0.02, 0.01, 0.03),
     True, "Cambio de rodamientos del compresor programado para el overhaul."),
    ("abc6", "MC561S001", 19, 1180, "other", (0.12, 0.25, 0.10, 0.18), (0.03, 0.05, 0.02, 0.04),
     False, "Alineamiento de poleas con láser; juego de fajas nuevo."),
]

# Trains where only the motor is registered: the aligned machine still has a
# name on the aligner's screen.
DRIVEN = {"co2_n1": "COMPRESOR CO2 N. 1", "abc6": "COMPRESOR ALTERNATIVO ABC 6"}

# Corrective work that executes the September recommendations: (days after
# the round, start, hours or None while still open, TAG worked on, work
# types, other description, description, spare parts, TAGs whose September
# recommendation it completes, TAGs whose recommendation it leaves scheduled,
# alignment key).
MAINTENANCE = [
    (4, "08:00", 3.5, "B131013A", ["alignment"], "",
     "Alineamiento láser motor-bomba según la recomendación de la ronda de septiembre. Pata coja "
     "corregida en la pata posterior del motor con lainas de acero inoxidable.",
     "Lainas inox 0.05 y 0.10 mm", ["MB131013A", "B131013A"], [], "caldera3_br1"),
    (6, "14:00", 3.0, "MB501014", ["other"], "Nivelación del motor y liberación de tensión en bridas",
     "Se niveló el motor respecto a la voluta y se liberó la tensión de las bridas de succión y descarga "
     "(desfase de 3 mm). Impulsor inspeccionado: sin desgaste.",
     "Empaquetaduras de brida 4\" (2)", ["MB501014"], [], None),
    (9, "07:30", 5.5, "MB562002", ["bearing_change", "other"], "Reemplazo de impulsor por erosión",
     "Ajuste de pernos de anclaje. Impulsor con erosión en tres álabes: reemplazado. Cambio preventivo de "
     "rodamientos del motor.",
     "Impulsor de bronce 210 mm; rodamientos 6309-2Z/C3 y 6307-2Z/C3", ["MB562002"], [], None),
    (10, "08:00", 3.0, "MB131010A", ["alignment"], "",
     "Alineamiento láser motor-bomba. La revisión de rodamientos del motor queda programada para la "
     "parada de caldera.",
     "", ["B131010A"], ["MB131010A"], "caldera2_br1"),
    (12, "09:00", 3.0, "SP562004", ["balancing"], "",
     "Balanceo dinámico en sitio del impelente en un plano: 1X de 7.12 a 1.90 mm/s. Masa de corrección "
     "de 18 g a 135°.",
     "", ["SP562004"], [], None),
    (13, "08:00", 6.0, "MB501003", ["other", "balancing"], "Reemplazo de impulsor",
     "Impulsor con desprendimiento de material en dos álabes: reemplazado y balanceado en taller "
     "(grado G6.3).",
     "Impulsor de acero inoxidable", ["MB501003"], [], None),
    (16, "07:00", 8.5, "B131007B", ["bearing_change", "alignment"], "",
     "Cambio de rodamientos de la bomba y corrección de la base. Pata coja verificada antes de alinear: "
     "0.03 mm (límite 0.04 mm). Alineamiento láser al cierre.",
     "Rodamientos 6308-2Z/C3 (2); lainas inox", ["B131007B"], [], "caldera1_br2"),
    (17, "08:00", 3.0, "B131007A", ["alignment"], "",
     "Alineamiento láser motor-bomba y refuerzo del anclaje: pernos de 5/8\" reemplazados.",
     "Pernos de anclaje 5/8\" (4)", ["MB131007A", "B131007A"], [], "caldera1_br1"),
    (18, "08:00", 4.5, "C151001", ["alignment"], "",
     "Alineamiento láser motor-compresor. Poleas de transmisión inspeccionadas: sin desgaste en canales.",
     "", ["C151001"], [], "co2_n1"),
    (18, "13:30", 3.5, "C141002", ["alignment"], "",
     "Alineamiento láser motor-compresor. El cambio de rodamientos del compresor queda programado para el "
     "overhaul.",
     "", ["MC141002"], ["C141002"], "sabroe_n2"),
    (19, "08:00", 5.0, "MC561S001", ["alignment", "other"], "Cambio de juego de fajas",
     "Alineamiento de poleas con láser y cambio del juego de fajas B-68. Poleas sin desgaste en canales.",
     "Fajas B-68 (4)", ["MC561S001"], [], "abc6"),
    (20, "09:00", 3.0, "MSP561003", ["balancing"], "",
     "Balanceo dinámico en sitio del ventilador del motor eléctrico: de 7.37 a 2.10 mm/s.",
     "", ["MSP561003"], [], None),
    (22, "08:00", None, "MR562023", ["bearing_change"], "",
     "Cambio de rodamientos del motor en curso; el reductor queda en inspección de componentes internos.",
     "Rodamientos 6206-2Z/C3 y 6205-2Z/C3", [], ["MR562023", "R562023"], None),
]
SCHEDULED_ONLY = ["MSP562S001"]

# END · Espesores UT on the boilers' pressure parts: (name, TAG prefix,
# nominal wall in mm, where each point is).
ELEMENTS = [
    ("DOMO DE VAPOR", "DV", 12.70, "Casco del domo: P1-P3 lado izquierdo, P4-P6 lado derecho"),
    ("CABEZAL DE VAPOR", "CV", 10.97, "Cabezal de 8\" SCH 80: P1-P6 a lo largo del cabezal"),
    ("LÍNEA DE AGUA DE ALIMENTACIÓN", "LA", 8.56,
     "Tubería de 4\" SCH 80: P3 en el codo de descarga de la bomba"),
]
# Wall lost at each point of the feed-water line, by boiler: it wears at the
# elbow after the pump.
FEED_LINE_LOSS = {
    1: (0.25, 0.34, 0.16, 0.21, 0.38, 0.27),
    2: (0.44, 0.70, 0.94, 0.62, 0.51, 0.46),
    3: (1.12, 1.44, 1.65, 1.21, 0.88, 0.76),
}

# UT on the idlers of the malt and adjunct belt conveyors: (sector, group,
# rollers, roller → (state, thinnest point, wall there)).
ROLLER_GROUPS = [
    ("TRANSPORTE DE MALTA", "POLINES DE CARGA - TRANSPORTADOR DE MALTA", 12,
     {4: ("medium", 3, 7.86), 7: ("critical", 4, 5.92), 9: ("medium", 2, 7.61), 12: ("inaccessible", 0, 0)}),
    ("TRANSPORTE DE ADJUNTO", "POLINES DE CARGA - TRANSPORTADOR DE ADJUNTO", 8,
     {3: ("medium", 5, 7.94)}),
]
ROLLER_WALL = 8.18


class Api:
    """The application's own API, signed in as one person of one company."""

    def __init__(self, user: User, tenant: str):
        from rest_framework.test import APIClient
        from rest_framework_simplejwt.tokens import AccessToken

        self.client = APIClient()
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}",
            HTTP_X_TENANT=tenant,
            HTTP_HOST="localhost",
        )

    def __call__(self, method: str, path: str, body=None, files: dict | None = None):
        url = f"/api/v1/{path}"
        if files:
            response = getattr(self.client, method)(url, {**(body or {}), **files}, format="multipart")
        else:
            response = getattr(self.client, method)(url, body, format="json")
        if response.status_code >= 400:
            detail = response.content[:400]
            raise CommandError(f"{method.upper()} {path} → {response.status_code}: {detail!r}")
        return response.json() if response.content else None


class Command(BaseCommand):
    help = "Diagnoses, corrective work, alignments, END thickness and UT on rollers"

    def add_arguments(self, parser) -> None:
        parser.add_argument("--seed", type=int, default=20261013)

    def handle(self, *args, **options) -> None:
        self.rng = random.Random(options["seed"])
        self.people = {role: User.objects.filter(email=email).first() for role, email in PEOPLE.items()}
        admin = self.people["admin"]
        if admin is None:
            raise CommandError("No existe admin@simiai.pe: es quien firma las llamadas a la API")
        for role, user in self.people.items():
            self.people[role] = user or admin
        self.api = Api(admin, current_tenant())

        september = ServiceOrder.objects.filter(code=SEPTEMBER).first()
        if september is None:
            raise CommandError(f"Falta la orden {SEPTEMBER}: es la ronda de la que cuelga todo")
        self.anchor = september.scheduled_to
        self.plant_id = september.plant_id
        self.provider_id = september.provider_id
        self.instruments = self._instruments()
        self.alignment_ids: dict[str, int] = {}

        for label, part in (
            ("Diagnósticos de julio", self._july),
            ("Alineamientos", self._alignments),
            ("Mantenimiento", self._maintenance),
            ("END · Espesores", self._thickness),
            ("UT en rodillos", self._rollers),
        ):
            with transaction.atomic(using=current_alias()):
                self.stdout.write(f"{label}: {part()}")

    # ---------------------------------------------------------------- helpers

    def _day(self, offset: int) -> date:
        # Never in the future: a record dated tomorrow would read as made up.
        return min(self.anchor + timedelta(days=offset), timezone.localdate() - timedelta(days=1))

    def _at(self, day: date, clock: str = "08:00") -> datetime:
        hour, minute = (int(part) for part in clock.split(":"))
        return timezone.make_aware(datetime.combine(day, time(hour, minute)))

    def _equipment(self, tag: str) -> Equipment:
        found = (
            Equipment.objects.filter(client_tag=tag, retired_at__isnull=True)
            .select_related("asset_group")
            .first()
        )
        if found is None:
            raise CommandError(f"No hay equipo con TAG {tag}")
        return found

    def _instruments(self) -> dict[str, int]:
        wanted = {
            "olympus_38dl": ("Medidor de espesores 38DL Plus", "Olympus"),
            "skf_tksa41": ("Alineador láser TKSA 41", "SKF"),
            "easy_laser_xt": ("Alineador láser de poleas XT190", "Easy-Laser"),
        }
        listed = {row["code"]: row["id"] for row in self.api("get", "instruments/")}
        for code, (name, maker) in wanted.items():
            if code not in listed:
                body = {"code": code, "name": name, "manufacturer": maker}
                listed[code] = self.api("post", "instruments/", body)["id"]
        return listed

    def _order(self, code: str, technique: str, start: int, end: int, standard=None) -> ServiceOrder:
        body = {
            "plant": self.plant_id, "technique": technique, "code": code,
            "client_work_order": f"OT-{1390100 + start}", "provider": self.provider_id,
            "lead_analyst": self.people["analyst"].id,
            "scheduled_from": self._day(start).isoformat(), "scheduled_to": self._day(end).isoformat(),
        }
        if standard:
            body["standard"] = standard
        return ServiceOrder.objects.get(id=self.api("post", "service-orders/new/", body)["id"])

    def _visit(self, order: ServiceOrder, equipment: Equipment, when: datetime, instrument=None) -> int:
        body = {"service_order": order.id, "equipment": equipment.id, "visited_at": when.isoformat()}
        if instrument:
            body["instrument"] = instrument
        return self.api("post", "service-visits/", body)["visit_id"]

    def _crew(self, visit_ids, lead: User, assistant: User | None = None) -> None:
        """The API makes whoever is signed in the lead; the work was theirs."""
        VisitParticipant.objects.filter(visit_id__in=visit_ids, user=self.people["admin"]).update(user=lead)
        if assistant and assistant != lead:
            for visit_id in visit_ids:
                VisitParticipant.objects.get_or_create(
                    visit_id=visit_id, user=assistant, defaults={"role": "assistant"}
                )
        Reading.objects.filter(service_visit_id__in=visit_ids).update(operator=assistant or lead)

    def _entry(self, visit_id: int, kind: str, text: str, author: User) -> int:
        body = {"entry_type": kind, "text": text}
        entry_id = self.api("post", f"service-visits/{visit_id}/entries/", body)["id"]
        EquipmentLogEntry.objects.filter(id=entry_id).update(author=author)
        return entry_id

    def _close(self, order: ServiceOrder, visit_ids) -> None:
        for visit_id in visit_ids:
            self.api("patch", f"service-visits/{visit_id}/edit/", {"close": True})
        self.api("patch", f"service-orders/{order.id}/", {"status": "done"})

    # ---------------------------------------------------------- July findings

    def _july(self) -> str:
        july = ServiceOrder.objects.filter(code=JULY).first()
        if july is None:
            return f"sin la orden {JULY}"
        analyst, made = self.people["analyst"], 0
        for tag, (faults, conclusion) in JULY_FINDINGS.items():
            equipment = self._equipment(tag)
            visit = ServiceVisit.objects.filter(service_order=july, equipment=equipment).first()
            if visit is None or visit.log_entries.filter(entry_type__in=("finding", "conclusion")).exists():
                continue
            worst = (
                Reading.objects.filter(service_visit=visit, magnitude__code="vel_rms", value__isnull=False)
                .select_related("point", "condition_status")
                .order_by("-condition_status__severity", "-value")
                .first()
            )
            if worst is None:
                continue
            before = (
                Reading.objects.filter(service_visit__service_order__code=JUNE, point=worst.point,
                                       magnitude__code="vel_rms", value__isnull=False)
                .values_list("value", flat=True)
                .first()
            )
            status = worst.condition_status.name.lower() if worst.condition_status else "sin evaluar"
            finding = (
                f"Velocidad vibracional de {worst.value:.2f} mm/s RMS en el punto {worst.point.label} de "
                f"{equipment.name} {tag}, en {status}."
                + (f" En junio marcaba {before:.2f} mm/s." if before is not None else "")
            )
            self._entry(visit.id, "finding", finding, analyst)
            self._entry(visit.id, "conclusion", conclusion, analyst)
            recommendation = self._entry(visit.id, "recommendation", JULY_RECOMMENDATION, analyst)
            # The September round was that follow-up.
            self.api("patch", f"log-entries/{recommendation}/", {"status": "done"})
            self.api("put", f"service-visits/{visit.id}/faults/", {"codes": faults})
            made += 1
        return f"{made} conjuntos con hallazgo, conclusión y recomendación"

    # --------------------------------------------------------------- alignment

    def _alignments(self) -> str:
        from modules.alignment.models import AlignmentRecord
        from modules.diagnostics.models import FaultMode
        from modules.thresholds.models import ThresholdStandard

        norma = ThresholdStandard.objects.filter(code="skf_alignment").first()
        fault = FaultMode.objects.filter(code="misalignment_parallel").first()
        order = ServiceOrder.objects.filter(code=ALIGNMENT_ORDER).first()
        new_order = order is None
        if new_order:
            days = [row[2] for row in ALIGNMENTS if row[7]]
            order = self._order(ALIGNMENT_ORDER, "alignment", min(days), max(days))
        made, visits = 0, []
        for key, tag, offset, rpm, aligner, before, after, in_order, note in ALIGNMENTS:
            driver = self._equipment(tag)
            group = driver.asset_group
            existing = AlignmentRecord.objects.filter(asset_group=group).order_by("-id").first()
            if existing is not None:
                self.alignment_ids[key] = existing.id
                continue
            day = self._day(offset)
            visit_id = None
            if in_order and new_order:
                when = self._at(day, "09:00")
                visit_id = self._visit(order, driver, when, self.instruments["skf_tksa41"])
                visits.append(visit_id)
            driven = group.equipments.exclude(id=driver.id).order_by("order_in_group", "id").first()
            driven_label = f"{driven.name} {driven.client_tag}".strip() if driven else DRIVEN.get(key, "")
            body = {
                "asset_group": group.id, "service_visit": visit_id,
                "driver_label": f"{driver.name} {driver.client_tag}".strip(),
                "driven_label": driven_label,
                "rpm": rpm, "aligner": aligner,
                "instrument": "SKF TKSA 41" if aligner == "skf" else "Easy-Laser XT190",
                "standard": norma.id if norma else None, "backlash_within_tolerance": True,
                "notes": note, "diagnosed_fault": fault.id if fault and before != after else None,
            }
            axes = ("angular_h", "parallel_h", "angular_v", "parallel_v")
            for phase, values in (("before", before), ("after", after)):
                for axis, value in zip(axes, values, strict=True):
                    body[f"{phase}_{axis}"] = str(value)
            record = self.api("post", "alignment-records/", body)
            AlignmentRecord.objects.filter(id=record["id"]).update(
                created_by=self.people["aligner"], created_at=self._at(day, "11:00")
            )
            self.alignment_ids[key] = record["id"]
            self._aligner_images(record["id"], aligner, body, before, after, rpm)
            if visit_id:
                self._entry(visit_id, "conclusion", _alignment_summary(before, after), self.people["aligner"])
            made += 1
        if visits:
            self._crew(visits, self.people["aligner"], self.people["inspector"])
            self._close(order, visits)
        return f"{made} alineamientos ({len(visits)} en la orden {ALIGNMENT_ORDER})"

    def _aligner_images(self, record_id: int, aligner: str, body: dict, before, after, rpm: int) -> None:
        title = f"{body['driver_label']} → {body['driven_label']} · {rpm} rpm"
        path = f"alignment-records/{record_id}/photos/"
        if aligner == "skf":
            image = _aligner_screen("SKF TKSA 41 · Resultado", title, (("Antes", before), ("Después", after)))
            caption = {"kind": "alignment_result", "caption": "Pantalla de resultado del alineador"}
            self.api("post", path, caption, files={"file": image})
            return
        phases = (("alignment_before", "Antes", before), ("alignment_after", "Después", after))
        for kind, label, values in phases:
            image = _aligner_screen(f"Easy-Laser XT190 · {label}", title, ((label, values),))
            caption = {"kind": kind, "caption": f"Lectura del alineador: {label.lower()}"}
            self.api("post", path, caption, files={"file": image})

    # ------------------------------------------------------------- maintenance

    def _maintenance(self) -> str:
        from modules.maintenance.models import WorkRecord

        recommendations = {
            entry.equipment.client_tag: entry
            for entry in EquipmentLogEntry.objects.filter(
                service_visit__service_order__code=SEPTEMBER, entry_type="recommendation"
            ).select_related("equipment")
        }
        crew = [{"user": self.people["technician"].id}, {"external_name": "Mecánicos AMBEV - turno A"}]
        made = 0
        for offset, start, hours, tag, types, other, description, parts, done, scheduled, key in MAINTENANCE:
            equipment = self._equipment(tag)
            day = self._day(offset)
            if WorkRecord.objects.filter(asset_group=equipment.asset_group, shift_date=day).exists():
                continue
            begin = self._at(day, start)
            completes = recommendations.get(done[0]) if done else None
            body = {
                "asset_group": equipment.asset_group_id, "equipment": equipment.id, "work_types": types,
                "other_description": other, "started_at": begin.isoformat(),
                "description": description, "spare_parts_used": parts,
                "client_work_order": f"OT-MC-{4100 + offset}", "responsibles": crew,
                "recommendation": completes.id if completes else None,
                "alignment_record": self.alignment_ids.get(key) if key else None,
            }
            if hours is not None:
                body["ended_at"] = (begin + timedelta(hours=hours)).isoformat()
            record = self.api("post", "work-records/", body)
            WorkRecord.objects.filter(id=record["id"]).update(created_by=self.people["technician"])
            if hours is not None:
                self.api("patch", f"work-records/{record['id']}/", {"close": True})
            for tags, status in ((done, "done"), (scheduled, "scheduled")):
                for rec_tag in tags:
                    if rec_tag in recommendations:
                        self.api("patch", f"log-entries/{recommendations[rec_tag].id}/", {"status": status})
            made += 1
        for rec_tag in SCHEDULED_ONLY:
            entry = recommendations.get(rec_tag)
            if entry is not None and entry.status == "open":
                self.api("patch", f"log-entries/{entry.id}/", {"status": "scheduled"})
        return f"{made} registros correctivos"

    # ------------------------------------------------------- END · thickness

    def _thickness(self) -> str:
        if ServiceOrder.objects.filter(code=THICKNESS_ORDER).exists():
            return "ya estaba"
        from modules.assets.models import AssetGroupKind

        standalone = AssetGroupKind.objects.filter(code="standalone").first()
        order = self._order(THICKNESS_ORDER, "ndt_thickness", 17, 19)
        inspector, analyst = self.people["inspector"], self.people["analyst"]
        visits, flagged = [], 0
        for boiler in (1, 2, 3):
            sector = Sector.objects.filter(name=f"CALDERA {boiler} ATA").first()
            if sector is None:
                continue
            group = AssetGroup.objects.filter(sector=sector, name="PARTES A PRESIÓN").first()
            if group is None:
                body = {"sector": sector.id, "name": "PARTES A PRESIÓN", "criticality": 1,
                        "kind": standalone.id if standalone else None}
                group = AssetGroup.objects.get(id=self.api("post", "asset-groups/", body)["id"])
            day = self._day(16 + boiler)
            for index, (name, prefix, nominal, where) in enumerate(ELEMENTS):
                tag = f"{prefix}131{boiler:03d}"
                equipment = self._element(group, name, tag, first=index * 6 + 1)
                when = self._at(day, f"{9 + index}:00")
                visit_id = self._visit(order, equipment, when, self.instruments["olympus_38dl"])
                visits.append(visit_id)
                loss = (FEED_LINE_LOSS[boiler] if prefix == "LA"
                        else tuple(round(self.rng.uniform(0.05, 0.22), 2) for _ in range(6)))
                values = [round(nominal - drop, 2) for drop in loss]
                self._thickness_readings(visit_id, values)
                thinnest = min(values)
                point = values.index(thinnest) + 1
                lost = (nominal - thinnest) / nominal * 100
                self._entry(visit_id, "observation",
                            f"{where}. Mínimo {thinnest:.2f} mm en P{point}: {lost:.0f} % menos que el "
                            f"nominal de {nominal:.2f} mm.", inspector)
                if thinnest >= 8.0:
                    continue
                flagged += 1
                critical = thinnest < 7.0
                state = " Espesor por debajo del mínimo admisible." if critical else " Espesor en alarma."
                self._entry(visit_id, "conclusion",
                            f"Adelgazamiento de pared por erosión en P{point} de la {name.lower()} de la "
                            f"caldera {boiler}.{state}", analyst)
                self._entry(visit_id, "recommendation",
                            "Reemplazar el tramo del codo de descarga en la próxima parada de la caldera."
                            if critical else
                            "Repetir la medición en tres meses y programar el reemplazo del codo si la "
                            "pérdida continúa.", analyst)
        self._crew(visits, inspector)
        self._close(order, visits)
        return f"{len(visits)} elementos de 3 calderas medidos, {flagged} con adelgazamiento"

    def _element(self, group: AssetGroup, name: str, tag: str, first: int) -> Equipment:
        """A pressure part with its six thickness points. Numbers run across
        the group, as in every train; each part still calls its own P1 to P6."""
        equipment = Equipment.objects.filter(client_tag=tag).first()
        if equipment is not None:
            return equipment
        body = {"asset_group": group.id, "name": name, "equipment_type": "other", "client_tag": tag,
                "generate_points": False, "monitoring_frequency": "annual"}
        equipment = Equipment.objects.get(id=self.api("post", "equipments/new/", body)["id"])
        for offset in range(6):
            point = {"equipment": equipment.id, "number": first + offset, "axis": "N",
                     "point_type": "ultrasound"}
            point_id = self.api("post", "points/", point)["id"]
            MeasurementPoint.objects.filter(id=point_id).update(label=f"P{offset + 1}")
        return equipment

    def _thickness_readings(self, visit_id: int, values: list[float]) -> None:
        detail = self.api("get", f"service-visits/{visit_id}/")
        points = sorted(detail["points"], key=lambda row: row["number"])
        readings = [
            {"reading_id": value["reading_id"], "value": f"{wall:.2f}"}
            for point, wall in zip(points, values, strict=False)
            for value in point["values"]
            if value["magnitude_code"] == "thickness_mm"
        ]
        self.api("patch", f"service-visits/{visit_id}/readings/", {"readings": readings})

    # ---------------------------------------------------------- UT on rollers

    def _rollers(self) -> str:
        if ServiceOrder.objects.filter(code=ROLLERS_ORDER).exists():
            return "ya estaba"
        from modules.thresholds.models import ThresholdStandard

        norma = ThresholdStandard.objects.filter(code="ut_rollers_thickness").first()
        order = self._order(ROLLERS_ORDER, "ndt_rollers", 19, 20, norma.id if norma else None)
        measured = 0
        for index, (sector_name, name, count, special) in enumerate(ROLLER_GROUPS):
            sector = Sector.objects.filter(name=sector_name, area__code="211").first()
            if sector is None:
                continue
            groups = {row["name"]: row["id"] for row in self.api("get", "ut-rollers/groups/")}
            group_id = groups.get(name) or self.api(
                "post", "ut-rollers/groups/", {"sector": sector.id, "name": name}
            )["id"]
            self.api("post", f"ut-rollers/groups/{group_id}/rollers/", {"numbers": list(range(1, count + 1))})
            rollers = {
                row["number"]: row["id"] for row in self.api("get", f"ut-rollers/groups/{group_id}/rollers/")
            }
            rows, states = [], {}
            for number, roller_id in sorted(rollers.items()):
                state, at, wall = special.get(number, ("acceptable", 0, 0))
                states[number] = state
                rows.append(self._roller_row(roller_id, state, at, wall))
            self.api("post", f"ut-rollers/orders/{order.id}/sheet/", {"group": group_id, "rows": rows})
            measured += len(rows)
            if index == 0:
                self._journals(order, group_id, rollers)
            self._indications(order, rollers, special)
            self._roller_report(order, group_id, name, states)
        visits = list(ServiceVisit.objects.filter(service_order=order).values_list("id", flat=True))
        when = self._at(self._day(19), "09:30")
        ServiceVisit.objects.filter(id__in=visits).update(visited_at=when)
        Reading.objects.filter(service_visit_id__in=visits).update(taken_at=when)
        EquipmentLogEntry.objects.filter(service_visit_id__in=visits).update(entry_date=when.date())
        self._crew(visits, self.people["inspector"])
        self._close(order, visits)
        return f"{measured} polines en 2 transportadores"

    def _roller_row(self, roller_id: int, state: str, at: int, wall: float) -> dict:
        if state == "inaccessible":
            return {"equipment": roller_id, "values": [None] * 6, "inaccessible": True,
                    "observation": "Guarda soldada sobre el polín: sin acceso al tubo."}
        values = [round(ROLLER_WALL - self.rng.uniform(-0.12, 0.15), 2) for _ in range(6)]
        if at:
            values[at - 1] = wall
        observation = {
            "medium": f"Desgaste en la zona de carga: mínimo {wall:.2f} mm en P{at}.",
            "critical": f"Adelgazamiento severo en P{at} ({wall:.2f} mm): zona de impacto de la descarga.",
        }.get(state, "")
        return {"equipment": roller_id, "values": [f"{v:.2f}" for v in values], "observation": observation}

    def _journals(self, order: ServiceOrder, group_id: int, rollers: dict[int, int]) -> None:
        for side in ("drive", "transmission"):
            rows = []
            for number, roller_id in sorted(rollers.items()):
                covered = number == 12
                state = "Sin fisuras presentes en el muñón de polín."
                if side == "drive" and number == 7:
                    state = "Fisura circunferencial en el muñón, a 22 mm del rodamiento."
                rows.append({
                    "equipment": roller_id, "diameter_mm": "40.00", "external_length_mm": "55.00",
                    "total_length_mm": "1060.00", "access": "covered" if covered else "ok",
                    "access_note": "Guarda soldada" if covered else "",
                    "state_text": "" if covered else state,
                })
            body = {"group": group_id, "side": side, "rows": rows}
            self.api("post", f"ut-rollers/orders/{order.id}/journals/", body)

    def _indications(self, order: ServiceOrder, rollers: dict[int, int], special: dict) -> None:
        for number, (state, at, _wall) in special.items():
            if state == "critical":
                self.api("post", "ut-rollers/indications/", {
                    "equipment": rollers[number], "service_order": order.id, "kind": "crack",
                    "side": "drive", "length_mm": "6.50", "depth_mm": "1.20",
                    "position": "Muñón lado mando, a 22 mm del rodamiento",
                    "notes": "Indicación lineal confirmada con barrido angular a 45°.",
                })
            elif state == "medium" and at:
                self.api("post", "ut-rollers/indications/", {
                    "equipment": rollers[number], "service_order": order.id, "kind": "other",
                    "position": f"P{at}, zona de carga",
                    "notes": "Corrosión localizada con pérdida de espesor.",
                })

    def _roller_report(self, order: ServiceOrder, group_id: int, name: str, states: dict[int, str]) -> None:
        counts = {state: list(states.values()).count(state)
                  for state in ("acceptable", "medium", "critical", "inaccessible")}
        worst = [number for number, state in states.items() if state == "critical"]
        blocked = [number for number, state in states.items() if state == "inaccessible"]
        conclusions = (
            f"De {len(states)} polines: {counts['acceptable']} aceptables, {counts['medium']} en estado "
            f"medio, {counts['critical']} crítico(s) y {counts['inaccessible']} inaccesible(s)."
        )
        steps = []
        if worst:
            conclusions += (
                f" El polín {worst[0]} tiene adelgazamiento severo y una fisura en el muñón lado mando."
            )
            steps.append(f"Reemplazar el polín {worst[0]} antes del próximo arranque.")
        steps.append("Repetir la medición de los polines en estado medio en seis meses.")
        if blocked:
            steps.append(f"Retirar la guarda soldada del polín {blocked[0]} para poder inspeccionarlo.")
        path = f"ut-rollers/orders/{order.id}/groups/{group_id}/report/"
        self.api("patch", path, {"conclusions": conclusions, "recommendations": " ".join(steps)})
        caption = {"role": "plan", "caption": f"Plano de {name.lower()}"}
        self.api("post", f"{path}images/", caption, files={"file": _roller_plan(name, states)})


def _alignment_summary(before, after) -> str:
    if before == after:
        return "Verificación preventiva del alineamiento: dentro de tolerancia, no requirió corrección."
    return (
        f"Alineamiento láser corregido: paralelo H de {before[1]:.2f} a {after[1]:.2f} mm, paralelo V de "
        f"{before[3]:.2f} a {after[3]:.2f} mm y angular H de {before[0]:.2f} a {after[0]:.2f} mm/100 mm. "
        "Dentro de tolerancia al cierre."
    )


# ------------------------------------------------------------------- drawings
#
# Drawn, not photographed: there is no real image set in the repository. What
# they show is the record's own numbers, so the picture and the data agree.


def _font(size: int, bold: bool = False):
    from PIL import ImageFont

    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(f"/usr/share/fonts/truetype/dejavu/{name}", size)
    except OSError:
        return ImageFont.load_default()


def _png(image, name: str) -> SimpleUploadedFile:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def _aligner_screen(heading: str, title: str, phases) -> SimpleUploadedFile:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (960, 220 + 150 * len(phases)), "#0f172a")
    draw = ImageDraw.Draw(image)
    draw.text((32, 24), heading, fill="#f8fafc", font=_font(30, bold=True))
    draw.text((32, 70), title, fill="#94a3b8", font=_font(20))
    labels = ("Angular H", "Paralelo H", "Angular V", "Paralelo V")
    units = ("mm/100", "mm", "mm/100", "mm")
    y = 130
    for name, values in phases:
        draw.text((32, y), name, fill="#e2e8f0", font=_font(24, bold=True))
        for column, (label, unit, value) in enumerate(zip(labels, units, values, strict=True)):
            x = 32 + column * 228
            box = "#14532d" if value <= 0.05 else "#7f1d1d"
            draw.rounded_rectangle((x, y + 40, x + 210, y + 130), radius=12, fill=box)
            draw.text((x + 14, y + 50), label, fill="#e2e8f0", font=_font(18))
            draw.text((x + 14, y + 80), f"{value:.2f} {unit}", fill="#ffffff", font=_font(28, bold=True))
        y += 150
    return _png(image, "alineador.png")


STATE_COLORS = {
    "acceptable": "#16a34a", "medium": "#f59e0b", "critical": "#dc2626", "inaccessible": "#94a3b8",
}
STATE_NAMES = {
    "acceptable": "Aceptable", "medium": "Medio", "critical": "Crítico", "inaccessible": "Inaccesible",
}


def _roller_plan(name: str, states: dict[int, str]) -> SimpleUploadedFile:
    from PIL import Image, ImageDraw

    width = max(140 + 90 * len(states), 900)
    image = Image.new("RGB", (width, 420), "#ffffff")
    draw = ImageDraw.Draw(image)
    draw.text((30, 20), name, fill="#0f172a", font=_font(24, bold=True))
    subtitle = "Vista lateral del transportador · sentido de la carga →"
    draw.text((30, 56), subtitle, fill="#475569", font=_font(16))
    draw.line((60, 200, width - 60, 200), fill="#334155", width=6)
    for position, (number, state) in enumerate(sorted(states.items())):
        x = 110 + position * 90
        draw.ellipse((x - 30, 210, x + 30, 270), fill=STATE_COLORS[state], outline="#0f172a", width=3)
        left = x - 8 if number < 10 else x - 14
        draw.text((left, 228), str(number), fill="#ffffff", font=_font(20, bold=True))
    x = 30
    for state, color in STATE_COLORS.items():
        draw.rectangle((x, 330, x + 22, 352), fill=color)
        draw.text((x + 30, 330), STATE_NAMES[state], fill="#0f172a", font=_font(18))
        x += 190
    return _png(image, "plano.png")
