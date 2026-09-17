"""Loads a working prototype from the customer's own spreadsheets.

Everything here comes from `predictive-docs/`: the 462-equipment RGP, the
13-round trend sheet of EB 228 and the two inspection reports. Nothing is
invented that the sources do not support — where a number had to be generated
(the rounds before the ones on record) it is generated *consistently* with the
status the RGP recorded for that equipment, so the traffic light, the trends
and the reports tell the same story.

    manage.py tenants run ambev seed_demo --docs ../predictive-docs
"""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from modules.assets.domain.asset_code import generate as generate_code
from modules.assets.models import (
    Area,
    AssetGroup,
    AssetGroupComponent,
    AssetGroupKind,
    Equipment,
    MeasurementPoint,
    Plant,
    PointTemplate,
    Sector,
)
from modules.core.models import Company, InstalledModule
from modules.diagnostics.models import EquipmentLogEntry, FaultMode
from modules.operating_data.models import OperatingParameter
from modules.measurements.models import Instrument, Magnitude, Reading, Technique, Unit
from modules.security.models import Membership, Permission, Role, User
from modules.services.models import ServiceOrder, ServicePlan, ServiceVisit, VisitParticipant
from modules.thresholds.domain.defaults import (
    ALL_STATUSES,
    PROFILES,
    STANDARDS,
    TRANSLATIONS,
)
from modules.thresholds.models import (
    MachineClass,
    Status,
    TechniqueStatusOption,
    TechniqueStatusProfile,
    ThresholdBand,
    ThresholdSet,
    ThresholdStandard,
)

UNITS = [
    ("mm/s", "Milímetros por segundo", {"es": "Milímetros por segundo", "en": "Millimetres per second"}),
    ("gE", "Envolvente de aceleración", {"es": "Envolvente de aceleración", "en": "Acceleration envelope"}),
    ("g", "Aceleración", {"es": "Aceleración", "en": "Acceleration"}),
    ("°C", "Grados Celsius", {"es": "Grados Celsius", "en": "Degrees Celsius"}),
    ("dB", "Decibelios", {"es": "Decibelios", "en": "Decibels"}),
    ("PSI", "Libras por pulgada cuadrada", {"es": "Libras por pulgada cuadrada", "en": "Pounds per square inch"}),
    ("Hz", "Hercios", {"es": "Hercios", "en": "Hertz"}),
    ("rpm", "Revoluciones por minuto", {"es": "Revoluciones por minuto", "en": "Revolutions per minute"}),
    ("cSt", "Centistokes", {"es": "Centistokes", "en": "Centistokes"}),
    ("ppm", "Partes por millón", {"es": "Partes por millón", "en": "Parts per million"}),
    ("kV", "Kilovoltios", {"es": "Kilovoltios", "en": "Kilovolts"}),
    ("mgKOH/g", "Número ácido", {"es": "Miligramos de KOH por gramo", "en": "Milligrams KOH per gram"}),
]

TECHNIQUES = [
    ("vibration", "Análisis de vibraciones", "Vibration analysis", "vibration"),
    ("ultrasound", "Análisis de ultrasonido", "Ultrasound analysis", "ultrasound"),
    ("thermography", "Termografía", "Thermography", "thermography"),
    ("oil_analysis", "Análisis de aceite", "Oil analysis", "oil_analysis"),
    ("insulating_oil", "Aceite dieléctrico", "Insulating oil", "oil_analysis"),
    ("maintenance", "Mantenimiento", "Maintenance", "operating_data"),
    ("lubrication", "Lubricación", "Lubrication", "operating_data"),
    ("alignment", "Alineamiento", "Alignment", "operating_data"),
]

MAGNITUDES = [
    ("vel_rms", "vibration", "Velocidad vibracional", "Vibration velocity", "mm/s", "rms", 2),
    ("env_accel", "vibration", "Envolvente de aceleración", "Acceleration envelope", "gE", "peak", 2),
    ("temp", "thermography", "Temperatura", "Temperature", "°C", "max", 0),
    ("delta_temp", "thermography", "Diferencia de temperatura", "Temperature difference", "°C", "max", 1),
    ("us_db", "ultrasound", "Nivel de ultrasonido", "Ultrasound level", "dB", "avg", 1),
    ("viscosity_40", "oil_analysis", "Viscosidad a 40 °C", "Viscosity at 40 °C", "cSt", "avg", 1),
    ("water_ppm", "oil_analysis", "Contenido de agua", "Water content", "ppm", "avg", 0),
    ("dielectric_kv", "insulating_oil", "Rigidez dieléctrica", "Dielectric strength", "kV", "avg", 1),
]

# Limits transcribed from the reports, with their source.
THRESHOLDS = [
    # (magnitude, aggregation, unit, scope, ref, standard, class, low, high, rationale)
    ("vel_rms", "rms", "mm/s", "equipment_type", "motor", "iso_10816_3", "class_iii", "4.5", "7.1", ""),
    ("vel_rms", "rms", "mm/s", "equipment_type", "blower", "iso_10816_3", "class_iii", "4.5", "7.1", ""),
    ("vel_rms", "rms", "mm/s", "equipment_type", "fan", "iso_10816_3", "class_iii", "4.5", "7.1", ""),
    ("vel_rms", "rms", "mm/s", "equipment_type", "pump", "technical_associates", None, "5.4", "8.1", ""),
    ("vel_rms", "rms", "mm/s", "equipment_type", "compressor", "technical_associates", None, "5.4", "8.1", ""),
    ("vel_rms", "rms", "mm/s", "equipment_type", "gearbox", "technical_associates", None, "5.4", "8.1", ""),
    ("env_accel", "peak", "gE", "global", None, None, None, "2.5", "4.0", "Envolvente en Gs pico"),
    ("env_accel", "peak_to_peak", "gE", "global", None, None, None, "9.0", "15.0", "Envolvente en Gs pico-pico"),
    ("temp", "max", "°C", "global", None, None, None, "60", "80", "Criterio térmico general"),
    ("delta_temp", "max", "°C", "global", None, "neta_mts", None, "10", "30",
     "ΔT sobre equipo similar en igual carga, según NETA MTS"),
    ("us_db", "avg", "dB", "global", None, "iso_29821", None, "10", "20",
     "Incremento sobre la línea base del punto"),
    ("water_ppm", "avg", "ppm", "global", None, "iso_14830_1", None, "200", "500",
     "Contenido de agua en lubricante"),
]

ROLES = {
    "company_admin": ["*"],
    "engineer": [
        "assets.view_equipment", "assets.manage_equipment", "assets.manage_point",
        "measurements.view_reading", "measurements.add_reading", "measurements.edit_reading",
        "thresholds.view_set", "thresholds.manage_set", "thresholds.manage_status",
        "thresholds.manage_standard", "services.view", "services.view_authorship",
        "services.close_visit", "services.manage_order", "diagnostics.view",
        "diagnostics.add_entry", "diagnostics.close_recommendation", "reports.view",
        "reports.create", "reports.issue", "summaries.view", "summaries.export",
        "media.view", "media.upload", "blueprints.view", "nameplate.view",
        "core.manage_modules", "security.view_user", "licensing.view_status",
    ],
    "technician": [
        "assets.view_equipment", "measurements.view_reading", "measurements.add_reading",
        "services.view", "services.view_authorship", "media.view", "media.upload",
        "diagnostics.view", "diagnostics.add_entry", "summaries.view",
        "blueprints.view", "nameplate.view", "thresholds.view_set",
    ],
    "external_inspector": [
        "assets.view_equipment", "blueprints.view", "nameplate.view",
        "measurements.view_reading", "measurements.add_reading",
        "services.view", "services.view_authorship",
        "media.view", "media.upload", "diagnostics.view", "diagnostics.add_entry",
        "summaries.view",
    ],
    "client_viewer": [
        "assets.view_equipment", "measurements.view_reading", "summaries.view",
        "reports.view", "services.view",
    ],
}

PEOPLE = [
    ("carlos.balta@simiai.pe", "Carlos", "Balta", "CT", "engineer", False),
    ("henry.tejada@contratista.pe", "Henry", "Tejada", "HT", "external_inspector", True),
    ("walter.g@contratista.pe", "Walter", "Gómez", "WG", "external_inspector", True),
    ("jorge.a@simiai.pe", "Jorge", "Aliaga", "JA", "technician", False),
    ("admin@simiai.pe", "Administrador", "SimiAI", "AD", "company_admin", False),
    ("cliente@ambev.com.pe", "Supervisión", "AMBEV", "SA", "client_viewer", False),
]

DEFAULT_PASSWORD = "predictive2026"


class Command(BaseCommand):
    help = "Seed a consistent prototype from the spreadsheets in predictive-docs"

    def add_arguments(self, parser):
        parser.add_argument("--docs", default="../predictive-docs")
        parser.add_argument("--rounds", type=int, default=6, help="Monthly rounds to generate")
        parser.add_argument("--seed", type=int, default=20140613)

    @transaction.atomic
    def handle(self, *args, **options):
        docs = Path(options["docs"]).expanduser().resolve()
        rgp = docs / "VIBRACION 2014 AMBEV - JUNIO.xls"
        if not rgp.exists():
            raise CommandError(f"RGP not found at {rgp}")
        random.seed(options["seed"])

        company = self._company()
        self._modules()
        statuses = self._statuses(company)
        units, techniques, magnitudes = self._catalogue()
        standards = self._standards(company, techniques)
        self._profiles(company, statuses, techniques)
        self._thresholds(company, statuses, standards, units)
        self._operating_parameters(company)
        users = self._users(company)
        instruments = self._instruments(company)

        plant = Plant.objects.create(
            company=company, code="huachipa", name="Planta Huachipa", address="Lima, Perú"
        )
        kinds = self._group_kinds(company)
        equipment = self._assets(company, plant, rgp, standards, statuses, kinds)
        self._readings(company, equipment, magnitudes, units, statuses, instruments, users,
                       plant, options["rounds"], docs)
        self._diary(company, equipment, users)

        self.stdout.write(self.style.SUCCESS(
            f"listo: {len(equipment)} equipos, "
            f"{MeasurementPoint.objects.count()} puntos, "
            f"{Reading.objects.count()} lecturas, "
            f"{ServiceVisit.objects.count()} visitas"
        ))
        self.stdout.write(f"usuarios: {', '.join(p[0] for p in PEOPLE)} / {DEFAULT_PASSWORD}")

    # ---------------------------------------------------------------- catalogue

    def _company(self) -> Company:
        return Company.objects.create(
            code="ambev", name="AMBEV Perú", tax_id="20330791501",
            timezone="America/Lima", default_language="es",
        )

    def _modules(self) -> None:
        from modules.core.infrastructure.discovery import discover_manifests

        # Only what is actually implemented. Marking `blueprints`, `diagnostics`
        # and `reports` as installed put them in the menu with no screen and no
        # endpoint behind them, which reads as a broken router.
        for manifest in discover_manifests():
            installed = manifest.is_core or manifest.auto_install or manifest.code in {
                "vibration", "ultrasound", "thermography", "operating_data", "nameplate",
                "diagnostics",
            }
            InstalledModule.objects.create(
                code=manifest.code,
                state="installed" if installed else "uninstalled",
                installed_version=manifest.version if installed else "",
                installed_at=timezone.now() if installed else None,
            )

    def _statuses(self, company: Company) -> dict[str, Status]:
        created = {}
        for status in ALL_STATUSES:
            created[status.code] = Status.objects.create(
                company=company, code=status.code, name=status.name, kind=status.kind.value,
                severity=status.severity, color=status.color,
                requires_action=status.requires_action, is_terminal=status.is_terminal,
                measurable=status.measurable,
                translations={"name": TRANSLATIONS.get(status.code, {})},
            )
        return created

    def _standards(self, company: Company, techniques) -> dict[str, ThresholdStandard]:
        created = {}
        for standard in STANDARDS:
            row = ThresholdStandard.objects.create(
                company=company, code=standard.code, name=standard.name,
                source=standard.source, is_builtin=True,
            )
            # A standard judges the service type it was written for.
            row.techniques.set([
                techniques[code] for code in standard.techniques if code in techniques
            ])
            for order, machine_class in enumerate(standard.machine_classes):
                MachineClass.objects.create(
                    standard=row, code=machine_class.code, name=machine_class.name,
                    description=machine_class.description, order=order,
                )
            created[standard.code] = row
        return created

    def _catalogue(self):
        units = {
            code: Unit.objects.create(code=code, name=name, translations={"name": tr})
            for code, name, tr in UNITS
        }
        techniques = {
            code: Technique.objects.create(
                code=code, name=name_es, module_code=module,
                translations={"name": {"es": name_es, "en": name_en}},
            )
            for code, name_es, name_en, module in TECHNIQUES
        }
        magnitudes = {
            code: Magnitude.objects.create(
                code=code, technique=techniques[technique], name=name_es,
                default_unit=units[unit], default_aggregation=aggregation, decimals=decimals,
                translations={"name": {"es": name_es, "en": name_en}},
            )
            for code, technique, name_es, name_en, unit, aggregation, decimals in MAGNITUDES
        }
        return units, techniques, magnitudes

    def _profiles(self, company, statuses, techniques) -> None:
        for profile in PROFILES:
            technique = techniques.get(profile.technique_code)
            if technique is None:
                continue
            row = TechniqueStatusProfile.objects.create(company=company, technique=technique)
            for order, status in enumerate(profile.options):
                TechniqueStatusOption.objects.create(
                    profile=row, status=statuses[status.code], order=order
                )

    def _thresholds(self, company, statuses, standards, units) -> None:
        for (magnitude, aggregation, unit, scope, ref, standard, machine_class,
             low, high, rationale) in THRESHOLDS:
            self._threshold_set(
                company, statuses, standards, magnitude, aggregation, unit, scope, ref,
                standard, machine_class, low, high, rationale,
            )
        # The EB 228 override: stricter than the ISO, "de acuerdo a historial".
        self._eb228_override = (Decimal("4.5"), Decimal("6.5"))

    def _threshold_set(self, company, statuses, standards, magnitude, aggregation, unit,
                       scope, ref, standard_code, machine_class_code, low, high, rationale,
                       author=None):
        standard = standards.get(standard_code) if standard_code else None
        machine_class = (
            MachineClass.objects.filter(standard=standard, code=machine_class_code).first()
            if standard and machine_class_code else None
        )
        threshold = ThresholdSet.objects.create(
            company=company, standard=standard, machine_class=machine_class,
            scope=scope, scope_ref_id=str(ref) if ref is not None else None,
            magnitude_code=magnitude, unit_code=unit, aggregation=aggregation,
            valid_from=date(2013, 1, 1), rationale=rationale, author=author,
        )
        ThresholdBand.objects.bulk_create([
            ThresholdBand(threshold_set=threshold, status=statuses["operational"],
                          min_value=None, max_value=Decimal(low), order=0),
            ThresholdBand(threshold_set=threshold, status=statuses["alarm"],
                          min_value=Decimal(low), max_value=Decimal(high), order=1),
            ThresholdBand(threshold_set=threshold, status=statuses["shutdown"],
                          min_value=Decimal(high), max_value=None, order=2),
        ])
        return threshold

    def _users(self, company) -> dict[str, User]:
        permissions = {}
        from modules.core.infrastructure.discovery import discover_manifests

        for manifest in discover_manifests():
            for code, description in manifest.permissions:
                permissions[code] = Permission.objects.create(
                    code=code, module_code=manifest.code, description=description
                )

        roles = {}
        for code, granted in ROLES.items():
            role = Role.objects.create(company=company, code=code, name=code.replace("_", " ").title())
            role.permissions.set(
                permissions.values() if granted == ["*"]
                else [permissions[p] for p in granted if p in permissions]
            )
            roles[code] = role

        users = {}
        for email, first, last, initials, role_code, is_external in PEOPLE:
            user = User.objects.create_user(
                email=email, password=DEFAULT_PASSWORD, first_name=first, last_name=last,
                initials=initials, is_external=is_external, language="es",
            )
            Membership.objects.create(
                user=user, company=company, role=roles[role_code], is_default=True
            )
            users[initials] = user
        users["ADMIN"] = users["AD"]
        return users

    def _operating_parameters(self, company) -> None:
        """The columns that sit beside the vibration values in the real
        reports: frequency, suction and discharge pressure, running hours."""
        for order, (code, name_es, name_en, unit, technique, applies, cumulative) in enumerate(
            OPERATING_PARAMETERS
        ):
            OperatingParameter.objects.create(
                company=company, code=code, name=name_es, unit_code=unit,
                technique_code=technique, applies_to=applies, is_cumulative=cumulative,
                order=order, translations={"name": {"es": name_es, "en": name_en}},
            )

    def _instruments(self, company) -> dict[str, Instrument]:
        rows = [
            ("semapi_mx300", "DSP Logger MX300", "SEMAPI", "MX300-0142"),
            ("skf_gx75", "Microlog GX 75", "SKF", "GX75-2211"),
            ("flir_e60", "Cámara termográfica E60", "FLIR", "E60-7781"),
        ]
        return {
            code: Instrument.objects.create(
                company=company, code=code, name=name, manufacturer=manufacturer,
                serial_number=serial, last_calibration=date(2026, 3, 1),
                next_calibration=date(2027, 3, 1),
            )
            for code, name, manufacturer, serial in rows
        }

    # ------------------------------------------------------------------- assets

    def _group_kinds(self, company) -> dict:
        """The train taxonomy and the point layout each one measures.

        Straight from `MPd-AV-N°006-13-EB P-757`: motor on points 1 and 2,
        driven machine on 3 and 4, three axes each, with envelope and
        temperature read on the horizontal.
        """
        axes = {"H": ["vel_rms", "env_accel", "temp"], "V": ["vel_rms"], "A": ["vel_rms"]}
        sides = {0: ("free_end", "coupling_end"), 1: ("coupling_end", "opposite_coupling")}
        created = {}
        for code, name, components in GROUP_KINDS:
            kind = AssetGroupKind.objects.create(
                company=company, code=code, name=name, is_builtin=True,
                translations={"name": {"es": name}},
            )
            for index, (label, equipment_type, position) in enumerate(components):
                component = AssetGroupComponent.objects.create(
                    kind=kind, order=index, label=label,
                    equipment_type=equipment_type, position=position,
                )
                first = 1 + index * 2
                PointTemplate.objects.bulk_create([
                    PointTemplate(
                        kind=kind, component=component, number=first + offset, axis=axis,
                        side=sides.get(index, ("custom", "custom"))[offset],
                        magnitudes=magnitudes,
                        order=(first + offset) * 10 + list(axes).index(axis),
                    )
                    for offset in (0, 1)
                    for axis, magnitudes in axes.items()
                ])
            created[code] = kind
        return created

    def _assets(self, company, plant, rgp_path, standards, statuses, kinds) -> list[Equipment]:
        from modules.assets.infrastructure.importers.rgp_excel import read_rgp

        areas: dict[str, Area] = {}
        sectors: dict[tuple[str, str], Sector] = {}
        groups: dict[tuple[str, str], AssetGroup] = {}
        taken: set[str] = set()
        equipment: list[Equipment] = []

        iso = standards["iso_10816_3"]
        tac = standards["technical_associates"]
        class_iii = MachineClass.objects.filter(standard=iso, code="class_iii").first()

        for row in read_rgp(rgp_path):
            area = areas.get(row.area_code)
            if area is None:
                area = Area.objects.create(
                    company=company, plant=plant, code=row.area_code, name=row.area_name,
                    criticality=2 if row.area_code.startswith(("1", "3")) else 3,
                )
                areas[row.area_code] = area

            sector_key = (row.area_code, row.sector or "GENERAL")
            sector = sectors.get(sector_key)
            if sector is None:
                sector = Sector.objects.create(
                    company=company, area=area, name=row.sector or "GENERAL",
                    code=_slug(row.sector or "general")[:40],
                )
                sectors[sector_key] = sector

            group_key = (sector_key[0] + sector_key[1], row.group or row.equipment_name)
            group = groups.get(group_key)
            if group is None:
                group = AssetGroup.objects.create(
                    company=company, sector=sector,
                    code=_unique(_slug(f"{row.area_code}-{row.group}")[:58], taken),
                    name=row.group or row.equipment_name,
                    kind=kinds[_group_kind(row.group, row.equipment_type)],
                )
                groups[group_key] = group

            equipment_type = row.equipment_type or _type_from_name(row.equipment_name)
            code = generate_code(
                area_code=row.area_code, equipment_type=equipment_type,
                client_tag=row.client_tag, taken=taken,
            )
            taken.add(code)
            is_motor = equipment_type == "motor"

            item = Equipment.objects.create(
                company=company, asset_group=group, asset_code=code,
                client_tag=row.client_tag or "", name=row.equipment_name or equipment_type.title(),
                equipment_type=equipment_type,
                position_in_group="driver" if is_motor else "driven",
                monitoring_frequency=row.frequency or "monthly",
                applied_standard=iso if equipment_type in {"motor", "fan", "blower"} else tac,
                machine_class=class_iii if equipment_type in {"motor", "fan", "blower"} else None,
                condition_status=statuses.get(row.condition_status),
                availability_status=statuses.get(row.availability_status or "running"),
                condition_updated_at=timezone.now() - timedelta(days=random.randint(1, 95)),
                installed_at=date(2011, 1, 1),
            )
            item.rgp = row
            equipment.append(item)

            base = 1 if is_motor else 3
            MeasurementPoint.objects.bulk_create([
                MeasurementPoint(
                    company=company, equipment=item, number=base + offset, axis=axis,
                    side=("free_end" if offset == 0 else "coupling_end") if is_motor
                    else ("coupling_end" if offset == 0 else "opposite_coupling"),
                    point_type="bearing", label=f"{base + offset}{axis}",
                    blueprint_x=0.25 + 0.22 * (base + offset - 1),
                    blueprint_y=0.45 + (0.12 if axis == "V" else 0.0),
                )
                for offset in (0, 1)
                for axis in ("H", "V", "A")
            ])
        return equipment

    # ----------------------------------------------------------------- readings

    def _readings(self, company, equipment, magnitudes, units, statuses, instruments,
                  users, plant, rounds, docs) -> None:
        technique = magnitudes["vel_rms"].technique
        ServicePlan.objects.create(
            company=company, plant=plant, year=2026, name="Programa MPd 2026", status="active"
        )

        crew = [users["HT"], users["JA"], users["WG"]]
        supervisor = users["CT"]
        today = timezone.now()

        orders = []
        for index in range(rounds):
            when = today - timedelta(days=30 * (rounds - index - 1))
            order = ServiceOrder.objects.create(
                company=company, plant=plant, technique=technique,
                code=f"MPd-AV-N°{index + 1:03d}-26",
                client_work_order=f"OT-{1382630 + index}",
                scheduled_from=when.date(), scheduled_to=when.date() + timedelta(days=3),
                # The latest round is the one still being worked: its visits
                # stay open, so calling it "done" contradicts the visit count
                # shown right next to it.
                status="done" if index < rounds - 1 else "in_progress",
                lead_analyst=crew[index % len(crew)], supervisor=supervisor,
            )
            orders.append((order, when))

        points_by_equipment: dict[int, list[MeasurementPoint]] = {}
        for point in MeasurementPoint.objects.select_related("equipment"):
            points_by_equipment.setdefault(point.equipment_id, []).append(point)

        readings: list[Reading] = []
        visits: list[ServiceVisit] = []
        participants: list[VisitParticipant] = []

        for item in equipment:
            for index, (order, when) in enumerate(orders):
                visits.append(ServiceVisit(
                    company=company, service_order=order, equipment=item,
                    visited_at=when - timedelta(hours=item.id % 8),
                    availability_status=item.availability_status,
                    instrument=instruments["semapi_mx300" if item.id % 2 else "skf_gx75"],
                    duration_min=random.randint(8, 25),
                    # Only the latest round stays open, so there is something an
                    # inspector can still edit in the demo.
                    is_closed=index < len(orders) - 1,
                ))

        ServiceVisit.objects.bulk_create(visits, batch_size=500)
        # Drawn, not derived from the id: six visits per equipment made
        # `id % len(crew)` land every round on the same person, which is not
        # what a crew roster looks like and made the ownership rules untestable.
        for visit in ServiceVisit.objects.all():
            lead = random.choice(crew)
            participants.append(
                VisitParticipant(visit=visit, user=lead, role="lead_analyst")
            )
            if random.random() < 0.25:
                assistant = random.choice([u for u in crew if u != lead])
                participants.append(
                    VisitParticipant(visit=visit, user=assistant, role="assistant")
                )
            if random.random() < 0.15:
                participants.append(
                    VisitParticipant(visit=visit, user=supervisor, role="supervisor")
                )
        VisitParticipant.objects.bulk_create(participants, batch_size=500)

        lead_of = {
            row.visit_id: row.user
            for row in VisitParticipant.objects.filter(role="lead_analyst").select_related("user")
        }

        visits_by_equipment: dict[int, list[ServiceVisit]] = {}
        for visit in ServiceVisit.objects.order_by("visited_at"):
            visits_by_equipment.setdefault(visit.equipment_id, []).append(visit)

        for item in equipment:
            row = item.rgp
            item.last_visit = next(iter(reversed(visits_by_equipment.get(item.id, []))), None)
            measurable = item.availability_status is None or item.availability_status.measurable
            points = points_by_equipment.get(item.id, [])
            series = _trend_for(row.condition_status, len(orders))
            for index, visit in enumerate(visits_by_equipment.get(item.id, [])):
                for point in points:
                    for magnitude_code, scale in (("vel_rms", 1.0), ("env_accel", 0.55), ("temp", 12.0)):
                        magnitude = magnitudes[magnitude_code]
                        if not measurable:
                            readings.append(Reading(
                                company=company, taken_at=visit.visited_at, point=point,
                                service_visit=visit, magnitude=magnitude, value=None,
                                unit=magnitude.default_unit,
                                aggregation=magnitude.default_aggregation,
                                quality="not_measured",
                                not_measured_reason=_reason(item.availability_status),
                                operator=lead_of.get(visit.id, crew[0]),
                                instrument=visit.instrument,
                            ))
                            continue
                        value = _value(series[index], magnitude_code, point.axis, scale)
                        readings.append(Reading(
                            company=company, taken_at=visit.visited_at, point=point,
                            service_visit=visit, magnitude=magnitude,
                            value=value, unit=magnitude.default_unit,
                            aggregation=magnitude.default_aggregation,
                            condition_status=_status_for(value, magnitude_code, item, statuses),
                            operator=lead_of.get(visit.id, crew[0]),
                            instrument=visit.instrument, quality="ok",
                        ))
        Reading.objects.bulk_create(readings, batch_size=2000)
        self._settle_status(equipment, statuses)

    def _settle_status(self, equipment, statuses) -> None:
        """The traffic light must agree with the trend.

        The RGP only recorded a status for part of the plant; the rest would sit
        at "sin evaluar" while their charts clearly showed values. So the final
        condition is taken from the worst reading of the last round — which is
        what the system does in production anyway.
        """
        worst: dict[int, int] = {}
        latest = (
            Reading.objects.filter(quality="ok", condition_status__isnull=False)
            .order_by("point__equipment_id", "-taken_at")
            .values_list("point__equipment_id", "condition_status__severity", "taken_at")
        )
        newest_round: dict[int, object] = {}
        for equipment_id, severity, taken_at in latest:
            if equipment_id not in newest_round:
                newest_round[equipment_id] = taken_at
            if taken_at != newest_round[equipment_id]:
                continue
            worst[equipment_id] = max(worst.get(equipment_id, 0), severity)

        by_severity = {status.severity: status for status in statuses.values()
                       if status.kind == "condition"}
        for item in equipment:
            severity = worst.get(item.id)
            if severity is None:
                continue
            item.condition_status = by_severity[severity]
        Equipment.objects.bulk_update(equipment, ["condition_status"], batch_size=500)


    def _diary(self, company, equipment, users) -> None:
        """The conclusions and recommendations the analysts actually wrote.

        They are in the RGP, one per equipment, and they are the part of the
        service a customer reads first. Leaving them out of the demo made the
        execution screen look like a list of numbers with no findings.
        """
        faults = {
            code: FaultMode.objects.create(
                company=company, code=code, name=name_es, technique_code="vibration",
                translations={"name": {"es": name_es, "en": name_en}},
            )
            for code, name_es, name_en in FAULT_MODES
        }
        analyst = users["CT"]
        entries = []
        for item in equipment:
            row = item.rgp
            visit = item.last_visit
            if visit is None:
                continue
            when = visit.visited_at.date()
            if row.conclusion:
                entries.append(EquipmentLogEntry(
                    company=company, equipment=item, service_visit=visit,
                    entry_type="conclusion", entry_date=when, text=row.conclusion,
                    author=analyst, severity=_severity(row.condition_status),
                ))
            if row.recommendation:
                entries.append(EquipmentLogEntry(
                    company=company, equipment=item, service_visit=visit,
                    entry_type="recommendation", entry_date=when, text=row.recommendation,
                    author=analyst, status="open", severity=_severity(row.condition_status),
                ))
        EquipmentLogEntry.objects.bulk_create(entries, batch_size=500)

        # Link each conclusion to the fault modes its own wording names.
        for entry in EquipmentLogEntry.objects.filter(entry_type="conclusion"):
            lowered = entry.text.lower()
            matched = [faults[code] for code, keywords in FAULT_KEYWORDS.items()
                       if any(word in lowered for word in keywords)]
            if matched:
                entry.fault_modes.set(matched)


OPERATING_PARAMETERS = [
    # code, es, en, unit, technique ("" = any), applies_to, cumulative
    ("rpm", "Velocidad", "Speed", "rpm", "", [], False),
    ("freq_hz", "Frecuencia", "Frequency", "Hz", "", [], False),
    ("current_a", "Amperaje", "Current", "A", "", ["motor"], False),
    ("voltage_v", "Voltaje", "Voltage", "V", "", ["motor"], False),
    ("power_kw", "Potencia", "Power", "kW", "", ["motor"], False),
    ("power_factor", "Factor de potencia", "Power factor", "", "", ["motor"], False),
    ("running_hours", "Horas acumuladas", "Running hours", "h", "", [], True),
    ("suction_psi", "Presión de succión", "Suction pressure", "PSI", "", ["pump"], False),
    ("discharge_psi", "Presión de descarga", "Discharge pressure", "PSI", "", ["pump"], False),
    ("flushing_coupling_psi", "Presión flushing lado acople", "Flushing pressure, coupling end",
     "PSI", "", ["pump"], False),
    ("flushing_free_psi", "Presión flushing lado libre", "Flushing pressure, free end",
     "PSI", "", ["pump"], False),
    ("ambient_temp", "Temperatura ambiente", "Ambient temperature", "°C", "thermography", [], False),
    ("emissivity", "Emisividad", "Emissivity", "", "thermography", [], False),
    ("load_pct", "Carga", "Load", "%", "thermography", [], False),
    ("oil_hours", "Horas del lubricante", "Oil hours", "h", "oil_analysis", [], True),
]

GROUP_KINDS = [
    ("motor_pump", "Motor-Bomba", [("MOTOR", "motor", "driver"), ("BOMBA", "pump", "driven")]),
    ("motor_compressor", "Motor-Compresor",
     [("MOTOR", "motor", "driver"), ("COMPRESOR", "compressor", "driven")]),
    ("motor_turbine", "Motor-Turbina",
     [("MOTOR", "motor", "driver"), ("TURBINA", "turbine", "driven")]),
    ("motor_gearbox", "Motor-Reductor",
     [("MOTOR", "motor", "driver"), ("REDUCTOR", "gearbox", "driven")]),
    ("motor_fan", "Motor-Ventilador",
     [("MOTOR", "motor", "driver"), ("VENTILADOR", "fan", "driven")]),
    ("motor_blower", "Motor-Soplador",
     [("MOTOR", "motor", "driver"), ("SOPLADOR", "blower", "driven")]),
    ("standalone", "Equipo aislado", [("EQUIPO", "other", "driver")]),
]

FAULT_MODES = [
    ("misalignment", "Desalineamiento", "Misalignment"),
    ("mechanical_looseness", "Soltura mecánica", "Mechanical looseness"),
    ("bearing_wear", "Desgaste de rodamientos", "Bearing wear"),
    ("soft_foot", "Pata coja", "Soft foot"),
    ("induced_stress", "Tensiones inducidas", "Induced stress"),
    ("gmf", "Frecuencia de engrane (GMF)", "Gear mesh frequency"),
    ("lubrication", "Deficiencia de lubricación", "Lubrication deficiency"),
    ("belt_wear", "Desgaste de fajas o poleas", "Belt or pulley wear"),
]

FAULT_KEYWORDS = {
    "misalignment": ("desalinea", "desalinia", "dessalinea"),
    "mechanical_looseness": ("soltura", "juego radial"),
    "bearing_wear": ("rodamiento",),
    "soft_foot": ("pata coja",),
    "induced_stress": ("tension", "tensión"),
    "gmf": ("gmf", "engrane"),
    "lubrication": ("lubrica",),
    "belt_wear": ("faja", "polea"),
}


def _severity(condition_code: str | None) -> int:
    return {"shutdown": 1, "alarm": 2}.get(condition_code or "", 3)


# ---------------------------------------------------------------------- helpers

def _slug(value: str) -> str:
    cleaned = "".join(c if c.isalnum() else "-" for c in (value or "").lower())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-") or "x"


def _unique(candidate: str, taken: set[str]) -> str:
    if candidate not in taken:
        taken.add(candidate)
        return candidate
    for suffix in range(2, 9999):
        alternative = f"{candidate[:54]}-{suffix}"
        if alternative not in taken:
            taken.add(alternative)
            return alternative
    raise ValueError(candidate)


def _group_kind(group_name: str, equipment_type: str | None) -> str:
    name = (group_name or "").upper()
    if "BBA" in name or "BOMBA" in name:
        return "motor_pump"
    if "COMPRES" in name:
        return "motor_compressor"
    if "SOPLADOR" in name:
        return "motor_blower"
    if "VENTILADOR" in name:
        return "motor_fan"
    if "REDUCTOR" in name or "ACION" in name:
        return "motor_gearbox"
    return "standalone"


def _type_from_name(name: str) -> str:
    upper = (name or "").upper()
    for needle, equipment_type in (
        ("MOTOR", "motor"), ("BOMBA", "pump"), ("COMPRESOR", "compressor"),
        ("COMPRESSOR", "compressor"), ("REDUCTOR", "gearbox"), ("VENTILADOR", "fan"),
        ("SOPLADOR", "blower"), ("CHUMACERA", "bearing_housing"),
    ):
        if needle in upper:
            return equipment_type
    return "other"


def _reason(status) -> str:
    return {
        "off": "equipment_off", "retired": "retired", "out_of_service": "stopped",
    }.get(getattr(status, "code", ""), "equipment_off")


def _trend_for(condition_code: str | None, rounds: int) -> list[float]:
    """A plausible history that ends where the RGP says the equipment is.

    Values drift towards the final condition instead of jumping, so the trend
    chart and the traffic light agree — which is the whole point of seeding
    from the real statuses rather than sprinkling random numbers.
    """
    target = {"operational": 0.45, "alarm": 0.72, "shutdown": 1.15}.get(condition_code or "", 0.4)
    start = max(0.25, target - random.uniform(0.15, 0.45))
    step = (target - start) / max(rounds - 1, 1)
    return [round(start + step * index + random.uniform(-0.04, 0.04), 3) for index in range(rounds)]


def _value(level: float, magnitude_code: str, axis: str, scale: float) -> Decimal:
    axis_factor = {"H": 1.0, "V": 0.85, "A": 0.6}.get(axis, 1.0)
    if magnitude_code == "vel_rms":
        raw = level * 6.2 * axis_factor
    elif magnitude_code == "env_accel":
        raw = level * 3.4 * axis_factor
    else:
        raw = 34 + level * 26 * axis_factor
    return Decimal(str(round(max(raw, 0.1), 2)))


def _status_for(value: Decimal, magnitude_code: str, item, statuses) -> Status:
    limits = {
        "vel_rms": (Decimal("4.5"), Decimal("7.1")) if item.equipment_type in
        {"motor", "fan", "blower"} else (Decimal("5.4"), Decimal("8.1")),
        "env_accel": (Decimal("2.5"), Decimal("4.0")),
        "temp": (Decimal("60"), Decimal("80")),
    }[magnitude_code]
    if value < limits[0]:
        return statuses["operational"]
    if value < limits[1]:
        return statuses["alarm"]
    return statuses["shutdown"]
