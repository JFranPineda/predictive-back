"""Loads IPSA's plant from its own workbooks into the current tenant (V3-37).

    manage.py tenants add ipsa "Industrias del Papel — Planta Chaclacayo" --url …
    manage.py tenants migrate ipsa
    manage.py tenants run ipsa import_ipsa --docs ../predictive-docs --report import.md

`docs/v3/EQUIPOS PLANTA IPSA - SEPTIEMBRE/` holds 47 books, one per train, and
a summary. Each book becomes a train with its machines and points, one
vibration visit per dated column (grouped into one order per round date), its
antecedentes, estado actual and recomendaciones as diary lines, and — with
images — its schemas, spectra and thermograms. The 2P sheet is AMBEV's old
template left inside every book and is never read.

Additive and idempotent, like `seed_more`: a second run creates nothing. On an
empty tenant it first lays down the catalogue a fresh database lacks —
statuses, techniques, magnitudes, standards, roles — because the data
migrations only fill it for companies that already exist.

What could not be mapped as written goes to the import report, never silently
into the data.
"""

from __future__ import annotations

import importlib
from collections import Counter
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from modules.assets.domain.asset_code import generate as generate_code
from modules.assets.domain.builtin_kinds import BUILTIN_KINDS
from modules.assets.domain.ipsa import (
    Book,
    area_of,
    borrow_dates,
    component_type,
    kind_for,
    limit_of,
    load_condition,
    order_code,
)
from modules.assets.infrastructure.importers.ipsa_excel import read_book, read_summary
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
from modules.core.infrastructure.transactions import tenant_atomic
from modules.core.management.commands.seed_demo import (
    MAGNITUDES,
    OPERATING_PARAMETERS,
    ROLES,
    TECHNIQUES,
    UNITS,
)
from modules.core.models import (
    Company,
)
from modules.diagnostics.models import (
    EquipmentLogEntry,
    FaultMode,
)
from modules.licensing.infrastructure.context import current_alias
from modules.measurements.models import (
    Instrument,
    Magnitude,
    Reading,
    Technique,
    Unit,
)
from modules.operating_data.models import (
    OperatingParameter,
    OperatingReading,
)
from modules.security.models import (
    Membership,
    Permission,
    Role,
    User,
)
from modules.services.models import (
    ServiceOrder,
    ServiceProvider,
    ServiceVisit,
    VisitParticipant,
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

FOLDER = "docs/v3/EQUIPOS PLANTA IPSA - SEPTIEMBRE"
LIMA = ZoneInfo("America/Lima")
PASSWORD = "predictive2026"

PEOPLE = [
    # email, first, last, initials, role
    ("admin@simiai.pe", "Administrador", "SimiAI", "AD", "company_admin"),
    ("carlos.balta@simiai.pe", "Carlos", "Balta", "CB", "engineer"),
    ("suan.hilario@simiai.pe", "Suan", "Hilario", "SH", "technician"),
    ("cliente@ipsa.com.pe", "Supervisión", "IPSA", "SI", "client_viewer"),
]

# What IPSA contracts: vibration and thermography, with the diary, the
# operating conditions, the traffic light and the reports. Everything else
# stays installable from /settings/modules.
MODULES = (
    "core",
    "vibration",
    "thermography",
    "diagnostics",
    "operating_data",
    "nameplate",
    "summaries",
    "reports",
)

HEADLINES = {
    "vibration": "vel_rms",
    "thermography": "delta_temp",
    "ultrasound": "us_db",
    "oil_analysis": "viscosity_40",
    "insulating_oil": "dielectric_kv",
    "ndt_thickness": "thickness_mm",
}

# The limits most of the 47 books print. A book whose own table differs gets
# its own set on its machines, so the system grades as that book did.
DEFAULT_LIMITS = {
    ("vel_rms", "iso_20816_3"): (Decimal("4.5"), Decimal("7.1")),
    ("vel_rms", "iso_10816_3"): (Decimal("4.5"), Decimal("7.1")),
    ("vel_rms", "technical_associates"): (Decimal("5.3"), Decimal("8.1")),
    ("env_accel", None): (Decimal("2"), Decimal("2.5")),
}

# IPSA's four-level thermal scale (Q9), on the element's absolute Tmax: a norma
# of its own, chosen per thermography report. ALERTA sits between ALARMA and
# PARADA, so it is a condition status of its own.
IPSA_NORMA = (
    "escala_termica_ipsa",
    "Escala térmica IPSA",
    "Hoja TERMOGRAFÍA de EQUIPOS - CONCLUSIONES.xlsx (IPSA, 2025)",
)
IPSA_THERMAL = (
    ("operational", None, Decimal("82")),
    ("alarm", Decimal("82"), Decimal("121")),
    ("alert", Decimal("121"), Decimal("148")),
    ("shutdown", Decimal("148"), None),
)
ALERT = {
    "code": "alert",
    "name": "Alerta",
    "severity": 25,
    "color": "#ea580c",
    "translations": {"name": {"es": "Alerta", "en": "Alert"}},
}

INSTRUMENTS = {
    "vibration": ("skf_cmxa80", "SKF Microlog CMXA 80", "SKF"),
    "thermography": ("flir_e4", "Cámara termográfica E4", "FLIR"),
}


class Command(BaseCommand):
    help = "Imports IPSA's 47 monthly workbooks into the current tenant (V3-37)"

    def add_arguments(self, parser):
        parser.add_argument("--docs", default="../predictive-docs")
        parser.add_argument("--report", default="", help="Where to write the import report (markdown)")
        parser.add_argument("--no-images", action="store_true", help="Skip the embedded pictures")

    @tenant_atomic
    def handle(self, *args, **options):
        folder = Path(options["docs"]).expanduser().resolve() / FOLDER
        if not folder.exists():
            raise CommandError(f"IPSA workbooks not found at {folder}")
        self.alias = current_alias()
        self.made: Counter = Counter()
        self.notes: list[str] = []

        paths = sorted(folder.glob("Equipo*.xlsx"))
        books = [read_book(path) for path in paths]
        for book in books:
            borrow_dates(book, books)
        trains, pareto = read_summary(folder / "EQUIPOS - CONCLUSIONES.xlsx")

        company = self._company()
        self._modules()
        catalogue = self._catalogue(company)
        people = self._people(company)
        plant = self._get(
            Plant,
            "plant",
            company=company,
            code="chaclacayo",
            defaults={"name": "Planta Chaclacayo", "address": "Chaclacayo, Lima"},
        )
        self._ensure_plan_room(company, books)

        machines = {book.number: self._train(company, plant, book, trains, catalogue) for book in books}
        self._limits(company, books, machines, catalogue)
        rounds = self._rounds(company, plant, books, machines, catalogue, people)
        self._diary(company, books, machines, rounds, trains, people)
        if not options["no_images"]:
            self._images(company, paths, books, machines, rounds, people)
        verdicts = self._settle(books, machines, rounds, catalogue)

        report = self._report(books, trains, pareto, verdicts)
        if options["report"]:
            Path(options["report"]).write_text(report, encoding="utf-8")
        created = ", ".join(f"{kind} {count}" for kind, count in sorted(self.made.items()) if count) or "nada"
        self.stdout.write(self.style.SUCCESS(f"IPSA: {len(books)} conjuntos · creado: {created}"))
        if not options["report"]:
            self.stdout.write(report)

    # ------------------------------------------------------------ helpers

    def _get(self, model, tally: str, defaults: dict | None = None, **lookup):
        row, created = model.objects.get_or_create(defaults=defaults or {}, **lookup)
        if created:
            self.made[tally] += 1
        return row

    def _ensure_plan_room(self, company, books) -> None:
        """Checked before any machine is written: a plant the licence cannot
        hold loads none of it (V3-36)."""
        from django.conf import settings

        from modules.assets.infrastructure.plan_counts import equipment_in_plan
        from modules.licensing.application.license_service import PlanLimitReachedError, ensure_room
        from modules.licensing.infrastructure.context import current_tenant

        existing = set(Equipment.objects.filter(company=company).values_list("asset_group__code", "name"))
        adding = sum(1 for book in books for name in book.components() if (book.code, name) not in existing)
        if not adding or not current_tenant():
            return
        try:
            ensure_room(
                current_tenant(),
                "equipment",
                equipment_in_plan(company.id),
                secret=settings.LICENSE_SECRET,
                adding=adding,
            )
        except PlanLimitReachedError as cause:
            raise CommandError(str(cause)) from cause

    # ---------------------------------------------------------- catalogue

    def _company(self):
        return self._get(
            Company,
            "empresa",
            code="ipsa",
            defaults={
                "name": "Industrias del Papel S.A.",
                "timezone": "America/Lima",
                "default_language": "es",
            },
        )

    def _modules(self) -> None:
        from modules.core.infrastructure.discovery import discover_manifests
        from modules.core.interfaces.views import build_installer

        installer = build_installer()
        installed = {info.manifest.code for info in installer.catalog() if info.state == "installed"}
        # Every core module, not only `core`: licensing depends on nothing and
        # nothing depends on it, so it is never pulled in by another.
        core = [manifest.code for manifest in discover_manifests() if manifest.is_core]
        for code in (*core, *MODULES):
            if code not in installed:
                done = installer.install(code).installed
                installed.update(done)
                self.made["módulos"] += len(done)

    def _catalogue(self, company) -> dict:
        from modules.diagnostics.domain.catalogue import ALL_FAULTS
        from modules.measurements.domain.acceleration import ACCELERATION
        from modules.measurements.domain.families import family_for
        from modules.measurements.domain.magnitude_order import display_order_for
        from modules.measurements.domain.thermography import IR_TMAX_SPEC
        from modules.thresholds.domain.defaults import ALL_STATUSES, PROFILES, STANDARDS, TRANSLATIONS

        per_bearing = importlib.import_module(
            "modules.measurements.migrations.0005_magnitude_per_axis"
        ).PER_BEARING

        statuses = {
            status.code: self._get(
                Status,
                "estados",
                company=company,
                code=status.code,
                defaults={
                    "name": status.name,
                    "kind": status.kind.value,
                    "severity": status.severity,
                    "color": status.color,
                    "requires_action": status.requires_action,
                    "is_terminal": status.is_terminal,
                    "measurable": status.measurable,
                    "translations": {"name": TRANSLATIONS.get(status.code, {})},
                },
            )
            for status in ALL_STATUSES
        }
        units = {
            code: self._get(
                Unit, "unidades", code=code, defaults={"name": name, "translations": {"name": tr}}
            )
            for code, name, tr in [*UNITS, ("mm", "Milímetros", {"es": "Milímetros", "en": "Millimetres"})]
        }
        techniques = {}
        for code, name_es, name_en, module in [
            *TECHNIQUES,
            ("ndt_thickness", "END · Espesores UT", "NDT · UT thickness", "ultrasound"),
        ]:
            techniques[code] = self._get(
                Technique,
                "técnicas",
                code=code,
                defaults={
                    "name": name_es,
                    "module_code": module,
                    "family": family_for(code),
                    "headline_magnitude": HEADLINES.get(code, ""),
                    "close_requirement": "plan_required" if code == "topography" else "",
                    "evidence_only": code in ("ndt_penetrant", "ndt_magnetic"),
                    "translations": {"name": {"es": name_es, "en": name_en}},
                },
            )
        rows = [
            (code, technique, es, en, unit, aggregation, decimals, {})
            for code, technique, es, en, unit, aggregation, decimals in MAGNITUDES
        ]
        for spec in (ACCELERATION, IR_TMAX_SPEC):
            rows.append(
                (
                    spec.code,
                    spec.technique,
                    spec.name_es,
                    spec.name_en,
                    spec.unit,
                    spec.aggregation,
                    spec.decimals,
                    {
                        "per_axis": spec.per_axis,
                        "higher_is_worse": spec.higher_is_worse,
                        "short_code": getattr(spec, "short_code", ""),
                        "template_only": getattr(spec, "template_only", False),
                    },
                )
            )
        rows.append(
            (
                "thickness_mm",
                "ndt_thickness",
                "Espesor de pared",
                "Wall thickness",
                "mm",
                "min",
                2,
                {"higher_is_worse": False, "per_axis": False},
            )
        )
        magnitudes = {}
        for code, technique, es, en, unit, aggregation, decimals, extra in rows:
            defaults = {
                "technique": techniques[technique],
                "name": es,
                "default_unit": units[unit],
                "default_aggregation": aggregation,
                "decimals": decimals,
                "display_order": display_order_for(code),
                "translations": {"name": {"es": es, "en": en}},
                "per_axis": code not in per_bearing,
                "short_code": per_bearing.get(code, ""),
            }
            defaults.update({k: v for k, v in extra.items() if v not in ("", None)})
            magnitudes[code] = self._get(Magnitude, "magnitudes", code=code, defaults=defaults)

        standards = {}
        for standard in STANDARDS:
            row = self._get(
                ThresholdStandard,
                "normas",
                company=company,
                code=standard.code,
                defaults={"name": standard.name, "source": standard.source, "is_builtin": True},
            )
            row.techniques.add(*[techniques[c] for c in standard.techniques if c in techniques])
            for order, machine_class in enumerate(standard.machine_classes):
                self._get(
                    MachineClass,
                    "clases",
                    standard=row,
                    code=machine_class.code,
                    defaults={
                        "name": machine_class.name,
                        "description": machine_class.description,
                        "order": order,
                        "power_min_kw": machine_class.power_min_kw,
                        "power_max_kw": machine_class.power_max_kw,
                        "mounting": machine_class.mounting.value,
                    },
                )
            standards[standard.code] = row
        for profile in PROFILES:
            technique = techniques.get(profile.technique_code)
            if technique is None:
                continue
            row = self._get(TechniqueStatusProfile, "perfiles", company=company, technique=technique)
            for order, status in enumerate(profile.options):
                self._get(
                    TechniqueStatusOption,
                    "perfiles",
                    profile=row,
                    status=statuses[status.code],
                    defaults={"order": order},
                )
        for fault in ALL_FAULTS:
            self._get(
                FaultMode,
                "modos de falla",
                company=company,
                code=fault.code,
                defaults={
                    "name": fault.name_es,
                    "technique_code": fault.technique,
                    "typical_signature": fault.signature,
                    "iso_reference": fault.reference,
                    "translations": {"name": {"es": fault.name_es, "en": fault.name_en}},
                },
            )
        for order, (code, es, en, unit, technique, applies, cumulative) in enumerate(OPERATING_PARAMETERS):
            self._get(
                OperatingParameter,
                "parámetros",
                company=company,
                code=code,
                defaults={
                    "name": es,
                    "unit_code": unit,
                    "technique_code": technique,
                    "applies_to": applies,
                    "is_cumulative": cumulative,
                    "order": order,
                    "translations": {"name": {"es": es, "en": en}},
                },
            )
        # Pulper Nº 04's takes name the load it ran under (VACÍO, CARGA 1TN).
        self._get(
            OperatingParameter,
            "parámetros",
            company=company,
            code="load_condition",
            defaults={
                "name": "Condición de carga",
                "order": len(OPERATING_PARAMETERS) + 1,
                "translations": {"name": {"es": "Condición de carga", "en": "Load condition"}},
            },
        )
        # Book 029 printed the paper machine's speed where the dates go.
        self._get(
            OperatingParameter,
            "parámetros",
            company=company,
            code="line_speed",
            defaults={
                "name": "Velocidad de línea",
                "unit_code": "m/s",
                "order": len(OPERATING_PARAMETERS),
                "decimals": 0,
                "translations": {"name": {"es": "Velocidad de línea", "en": "Line speed"}},
            },
        )
        instruments = {
            technique: self._get(
                Instrument,
                "instrumentos",
                company=company,
                code=code,
                defaults={"name": name, "manufacturer": maker},
            )
            for technique, (code, name, maker) in INSTRUMENTS.items()
        }
        kinds = self._kinds(company)
        provider = self._get(ServiceProvider, "proveedores", company=company, name="1A-MIG")
        return {
            "statuses": statuses,
            "techniques": techniques,
            "magnitudes": magnitudes,
            "standards": standards,
            "instruments": instruments,
            "kinds": kinds,
            "provider": provider,
        }

    def _kinds(self, company) -> dict:
        from modules.assets.infrastructure.kind_layouts import write_layout

        kinds = {}
        for blueprint in BUILTIN_KINDS:
            kind, created = AssetGroupKind.objects.get_or_create(
                company=company,
                code=blueprint.code,
                defaults={
                    "name": blueprint.name,
                    "is_builtin": True,
                    "translations": {"name": {"es": blueprint.name, "en": blueprint.name_en}},
                },
            )
            if created:
                self.made["tipos de conjunto"] += 1
                write_layout(
                    kind,
                    blueprint.components,
                    component_model=AssetGroupComponent,
                    template_model=PointTemplate,
                    using=self.alias,
                )
            kinds[blueprint.code] = kind
        return kinds

    def _people(self, company) -> dict:
        active = {p.code: p for p in Permission.objects.filter(is_active=True)}
        roles = {}
        for code, granted in ROLES.items():
            role, created = Role.objects.get_or_create(
                company=company, code=code, defaults={"name": code.replace("_", " ").title()}
            )
            if created:
                self.made["roles"] += 1
                role.permissions.set(
                    active.values() if granted == ["*"] else [active[p] for p in granted if p in active]
                )
            roles[code] = role
        people = {}
        for email, first, last, initials, role_code in PEOPLE:
            user = User.objects.filter(email=email).first()
            if user is None:
                user = User.objects.create_user(
                    email=email,
                    password=PASSWORD,
                    first_name=first,
                    last_name=last,
                    initials=initials,
                    language="es",
                )
                self.made["usuarios"] += 1
            self._get(
                Membership,
                "membresías",
                user=user,
                company=company,
                defaults={"role": roles[role_code], "is_default": True},
            )
            people[initials] = user
        return people

    # ------------------------------------------------------------ structure

    def _train(self, company, plant, book: Book, trains: dict, catalogue: dict) -> dict:
        """The train, its machines (one per COMPONENTE) and their points."""
        area_code, area_name = area_of(book.area)
        area = self._get(
            Area, "áreas", company=company, plant=plant, code=area_code, defaults={"name": area_name}
        )
        sector = self._get(
            Sector, "sectores", company=company, area=area, code="general", defaults={"name": "GENERAL"}
        )
        types = [component_type(name) for name in book.components()]
        kind = catalogue["kinds"].get(kind_for(types))
        name = (trains.get(book.number) or {}).get("name") or book.header_name
        group = self._get(
            AssetGroup,
            "conjuntos",
            company=company,
            code=book.code,
            defaults={"sector": sector, "name": name, "kind": kind},
        )
        standards = catalogue["standards"]
        motor_standard = next(
            (
                standard
                for limit in book.limits
                if (found := limit_of(limit.label))
                and found[0] == "vel_rms"
                and (standard := found[1]) in ("iso_20816_3", "iso_10816_3")
            ),
            "iso_20816_3",
        )
        design = any(limit_of(limit.label) == ("vel_rms", "design") for limit in book.limits)
        taken = set(Equipment.objects.filter(company=company).values_list("asset_code", flat=True))
        slots = list(kind.components.order_by("order")) if kind else []
        machines = {}
        for order, component in enumerate(book.components()):
            equipment_type = component_type(component)
            standard = (
                None
                if design
                else (
                    standards["technical_associates"]
                    if equipment_type == "pump"
                    else standards[motor_standard]
                )
            )
            slot = next((s for s in slots if s.equipment_type == equipment_type), None)
            if slot:
                slots.remove(slot)
            item = Equipment.objects.filter(asset_group=group, name=component).first()
            if item is None:
                code = generate_code(
                    area_code=area_code, equipment_type=equipment_type, client_tag=None, taken=taken
                )
                taken.add(code)
                item = Equipment.objects.create(
                    company=company,
                    asset_group=group,
                    asset_code=code,
                    name=component,
                    equipment_type=equipment_type,
                    order_in_group=order,
                    group_component=slot,
                    position_in_group="driver" if equipment_type == "motor" else "driven",
                    applied_standard=standard,
                    monitoring_frequency="monthly",
                )
                self.made["equipos"] += 1
            points = {}
            for row in (r for r in book.rows if r.component == component):
                axis = row.axis or "H"
                point, created = MeasurementPoint.objects.get_or_create(
                    equipment=item,
                    number=row.point,
                    axis=axis,
                    defaults={"company": company, "side": row.side, "label": f"{row.point}{axis}"},
                )
                self.made["puntos"] += int(created)
                points[(row.point, axis)] = point
            machines[component] = (item, points)
        return {"group": group, "machines": machines}

    def _limits(self, company, books, machines, catalogue) -> None:
        """The tenant's limits, then each book's own where it differs."""
        standards, statuses = catalogue["standards"], catalogue["statuses"]
        for (magnitude, standard), (low, high) in DEFAULT_LIMITS.items():
            aggregation = "peak" if magnitude == "env_accel" else "rms"
            unit = "gE" if magnitude == "env_accel" else "mm/s"
            self._set(
                company,
                statuses,
                magnitude,
                aggregation,
                unit,
                "global",
                None,
                standards.get(standard) if standard else None,
                low,
                high,
                "Límite de los informes de IPSA"
                + (f" · {standards[standard].name}" if standard else " · envolvente en Gs pico"),
            )
        self._thermal_norma(company, catalogue)

        for book in books:
            for limit in book.limits:
                found = limit_of(limit.label)
                if found is None:
                    continue
                magnitude, standard = found
                default = DEFAULT_LIMITS.get((magnitude, None if standard == "design" else standard))
                if default == (limit.normal, limit.stop):
                    continue
                if limit.stop <= limit.normal:
                    self.notes.append(
                        f"{book.filename}: límite '{limit.label}' {_n(limit.normal)} / {_n(limit.stop)} "
                        "no es válido (parada ≤ alarma); se usa el de la planta"
                    )
                    continue
                pumps = standard == "technical_associates"
                for item, _ in machines[book.number]["machines"].values():
                    if magnitude == "vel_rms" and (item.equipment_type == "pump") != pumps:
                        continue
                    aggregation = "peak" if magnitude == "env_accel" else "rms"
                    unit = "gE" if magnitude == "env_accel" else "mm/s"
                    self._set(
                        company,
                        statuses,
                        magnitude,
                        aggregation,
                        unit,
                        "equipment",
                        item.id,
                        None,
                        limit.normal,
                        limit.stop,
                        f"Límite propio del libro {book.filename}: {limit.label}",
                    )
                self.notes.append(
                    f"{book.filename}: límite propio {_n(limit.normal)} / {_n(limit.stop)} "
                    f"({limit.label}) aplicado a sus equipos"
                )
            table = next((t for t in book.limits if limit_of(t.label) == ("vel_rms", "design")), None)
            applied = book.column_limits.get("alarma", set())
            if table and applied and applied != {table.normal}:
                shown = ", ".join(_n(v) for v in sorted(applied))
                self.notes.append(
                    f"{book.filename}: la tabla de límites dice alarma {_n(table.normal)} "
                    f"y las filas por columna {shown}; se usa la tabla"
                )

    def _thermal_norma(self, company, catalogue) -> None:
        """Q9: IPSA's scale as a norma of the Normas module, applied to
        thermography, with ALERTA as a fourth condition status."""
        statuses = catalogue["statuses"]
        alert = self._get(
            Status,
            "estados",
            company=company,
            code=ALERT["code"],
            defaults={
                "name": ALERT["name"],
                "kind": "condition",
                "severity": ALERT["severity"],
                "color": ALERT["color"],
                "requires_action": True,
                "measurable": True,
                "translations": ALERT["translations"],
            },
        )
        statuses[ALERT["code"]] = alert
        profile = TechniqueStatusProfile.objects.filter(
            company=company, technique=catalogue["techniques"]["thermography"]
        ).first()
        if profile is not None and not profile.options.filter(status=alert).exists():
            ladder = ("operational", "alarm", "alert", "shutdown")
            for option in profile.options.select_related("status"):
                code = option.status.code
                option.order = ladder.index(code) if code in ladder else len(ladder) + option.order
                option.save(update_fields=["order"])
            TechniqueStatusOption.objects.create(profile=profile, status=alert, order=ladder.index("alert"))

        code, name, source = IPSA_NORMA
        norma = self._get(
            ThresholdStandard,
            "normas",
            company=company,
            code=code,
            defaults={
                "name": name,
                "source": source,
                "translations": {"name": {"es": name}},
            },
        )
        norma.techniques.add(catalogue["techniques"]["thermography"])
        catalogue["thermal_norma"] = norma
        lookup = {
            "company": company,
            "magnitude_code": "ir_tmax",
            "aggregation": "max",
            "scope": "global",
            "scope_ref_id": None,
            "standard": norma,
            "machine_class": None,
        }
        if not ThresholdSet.objects.filter(**lookup).exists():
            row = ThresholdSet.objects.create(
                **lookup,
                unit_code="°C",
                valid_from=datetime(2024, 1, 1).date(),
                rationale="Escala térmica de IPSA: aceptable < 82 °C, alarma 82\u2013121, "
                "alerta 121\u2013148, parada \u2265 148",
            )
            ThresholdBand.objects.bulk_create(
                [
                    ThresholdBand(
                        threshold_set=row, status=statuses[status], min_value=low, max_value=high, order=order
                    )
                    for order, (status, low, high) in enumerate(IPSA_THERMAL)
                ]
            )
            self.made["umbrales"] += 1
        # The first import loaded this scale as a hand-written 3-band set on
        # `temp`, ALERTA folded into ALARMA; the norma replaces it.
        ThresholdSet.objects.filter(
            company=company,
            magnitude_code="temp",
            standard__isnull=True,
            scope="global",
            rationale__startswith="Escala térmica de IPSA",
            is_active=True,
        ).update(is_active=False)

    def _set(
        self, company, statuses, magnitude, aggregation, unit, scope, ref, standard, low, high, rationale
    ):
        lookup = {
            "company": company,
            "magnitude_code": magnitude,
            "aggregation": aggregation,
            "scope": scope,
            "scope_ref_id": str(ref) if ref is not None else None,
            "standard": standard,
            "machine_class": None,
        }
        if ThresholdSet.objects.filter(**lookup).exists():
            return
        row = ThresholdSet.objects.create(
            **lookup, unit_code=unit, valid_from=datetime(2024, 1, 1).date(), rationale=rationale
        )
        ThresholdBand.objects.bulk_create(
            [
                ThresholdBand(
                    threshold_set=row, status=statuses["operational"], min_value=None, max_value=low, order=0
                ),
                ThresholdBand(
                    threshold_set=row, status=statuses["alarm"], min_value=low, max_value=high, order=1
                ),
                ThresholdBand(
                    threshold_set=row, status=statuses["shutdown"], min_value=high, max_value=None, order=2
                ),
            ]
        )
        self.made["umbrales"] += 1

    # --------------------------------------------------------------- rounds

    def _rounds(self, company, plant, books, machines, catalogue, people) -> dict:
        """One visit per machine and dated column; one order per round date."""
        from modules.thresholds.application.evaluation import context_for
        from modules.thresholds.domain.services import evaluate, resolve
        from modules.thresholds.infrastructure.repositories import DjangoThresholdRepository

        statuses, magnitudes = catalogue["statuses"], catalogue["magnitudes"]
        technique = catalogue["techniques"]["vibration"]
        instrument = catalogue["instruments"]["vibration"]
        analyst, inspector = people["CB"], people["SH"]
        parameters = {p.code: p for p in OperatingParameter.objects.filter(company=company)}
        candidates = {
            code: DjangoThresholdRepository().candidates(company.id, code)
            for code in ("vel_rms", "env_accel")
        }
        existing = set(
            Reading.objects.filter(company=company).values_list(
                "service_visit_id", "point_id", "magnitude_id"
            )
        )
        rounds: dict[str, dict] = {}
        pending: list = []

        for book in books:
            train = machines[book.number]
            takes: Counter = Counter()
            for column in book.columns:
                has_values = any(column.index in row.values for row in book.rows)
                if column.day is None:
                    if has_values:
                        self.notes.append(
                            f"{book.filename}: columna con valores y sin fecha ({column.take}); no se importa"
                        )
                    continue
                if not has_values and column.state not in ("off", "no_access"):
                    continue
                takes[column.day] += 1
                code = order_code("vibration", column.day, takes[column.day])
                moment = datetime.combine(column.day, time(9 + takes[column.day] - 1), LIMA)
                order = self._get(
                    ServiceOrder,
                    "órdenes",
                    company=company,
                    code=code,
                    defaults={
                        "plant": plant,
                        "technique": technique,
                        "scheduled_from": column.day,
                        "scheduled_to": column.day,
                        "status": "done",
                        "provider": catalogue["provider"],
                        "lead_analyst": analyst,
                    },
                )
                entry = rounds.setdefault(book.number, {"visits": {}, "columns": []})
                visits = {}
                for component, (item, points) in train["machines"].items():
                    visit, created = ServiceVisit.objects.get_or_create(
                        service_order=order,
                        equipment=item,
                        defaults={
                            "company": company,
                            "visited_at": moment,
                            "instrument": instrument,
                            "availability_status": statuses["off" if column.state == "off" else "running"],
                            "is_closed": True,
                            "closed_at": moment + timedelta(hours=1),
                            "closed_by": analyst,
                        },
                    )
                    if created:
                        self.made["visitas"] += 1
                        VisitParticipant.objects.get_or_create(
                            visit=visit, user=analyst, defaults={"role": "lead_analyst"}
                        )
                        VisitParticipant.objects.get_or_create(
                            visit=visit, user=inspector, defaults={"role": "assistant"}
                        )
                    visits[component] = visit
                    for row in (r for r in book.rows if r.component == component):
                        point = points[(row.point, row.axis or "H")]
                        magnitude = magnitudes[row.magnitude]
                        if (visit.id, point.id, magnitude.id) in existing:
                            continue
                        value = row.values.get(column.index)
                        if value is None and column.state not in ("off", "no_access"):
                            continue
                        existing.add((visit.id, point.id, magnitude.id))
                        pending.append(
                            self._reading(
                                company,
                                visit,
                                point,
                                magnitude,
                                value,
                                column,
                                moment,
                                inspector,
                                instrument,
                                item,
                                candidates,
                                statuses,
                                context_for,
                                resolve,
                                evaluate,
                            )
                        )
                self._operating(company, book, column, visits, parameters, moment)
                entry["visits"][column.index] = visits
                entry["columns"].append((column, order))
        Reading.objects.bulk_create(pending, batch_size=1000)
        self.made["lecturas"] += len(pending)
        return rounds

    def _reading(
        self,
        company,
        visit,
        point,
        magnitude,
        value,
        column,
        moment,
        inspector,
        instrument,
        item,
        candidates,
        statuses,
        context_for,
        resolve,
        evaluate,
    ):
        aggregation = magnitude.default_aggregation
        if value is None:
            reason = "equipment_off" if column.state == "off" else "no_access"
            return Reading(
                company=company,
                taken_at=moment,
                point=point,
                service_visit=visit,
                magnitude=magnitude,
                value=None,
                unit=magnitude.default_unit,
                aggregation=aggregation,
                quality="not_measured",
                not_measured_reason=reason,
                notes=column.raw_state,
                operator=inspector,
                instrument=instrument,
            )
        chosen = resolve(
            candidates[magnitude.code], context_for(item, magnitude.code, aggregation, point.id), column.day
        )
        verdict = evaluate(value, chosen)
        return Reading(
            company=company,
            taken_at=moment,
            point=point,
            service_visit=visit,
            magnitude=magnitude,
            value=value,
            unit=magnitude.default_unit,
            aggregation=aggregation,
            quality="ok",
            condition_status=statuses.get(verdict.status.code) if verdict.status else None,
            threshold_set_id=verdict.threshold_set_id,
            operator=inspector,
            instrument=instrument,
        )

    def _operating(self, company, book, column, visits, parameters, moment) -> None:
        """Frequency and pressures (book 020) and the line speed (book 029)."""
        values = {code: series.get(column.index) for code, series in book.operating.items()}
        if column.speed is not None:
            values["line_speed"] = column.speed
        condition = load_condition(column.take)
        if condition:
            values["load_condition"] = condition
        for code, value in values.items():
            if value is None or code not in parameters:
                continue
            text = value if isinstance(value, str) else ""
            wanted = "pump" if code.endswith("_psi") else None
            visit = next(
                (v for v in visits.values() if wanted is None or v.equipment.equipment_type == wanted), None
            )
            if visit is None:
                continue
            _, created = OperatingReading.objects.get_or_create(
                service_visit=visit,
                parameter=parameters[code],
                defaults={
                    "company": company,
                    "equipment": visit.equipment,
                    "taken_at": moment,
                    "value": None if text else value,
                    "text_value": text,
                },
            )
            self.made["datos de operación"] += int(created)

    # ---------------------------------------------------------------- diary

    def _diary(self, company, books, machines, rounds, trains, people) -> None:
        """Antecedentes, estado actual and recomendaciones, dated, on the
        first machine of the train; the thermography sheet's on its own visit."""
        technique = Technique.objects.get(code="thermography")
        instrument = Instrument.objects.get(company=company, code="flir_e4")
        statuses = {s.code: s for s in Status.objects.filter(company=company)}
        analyst = people["CB"]
        kinds = {"background": "background", "present": "conclusion", "recommendation": "recommendation"}
        norma = ThresholdStandard.objects.get(company=company, code=IPSA_NORMA[0])

        for book in books:
            first = next(iter(machines[book.number]["machines"].values()))[0]
            latest = None
            if rounds.get(book.number, {}).get("columns"):
                _, last_order = rounds[book.number]["columns"][-1]
                latest = ServiceVisit.objects.filter(service_order=last_order, equipment=first).first()
            thermo = None
            if book.thermo_day:
                summary_state = (trains.get(book.number) or {}).get("thermography")
                order = self._get(
                    ServiceOrder,
                    "órdenes",
                    company=company,
                    code=order_code("thermography", book.thermo_day, 1),
                    defaults={
                        "plant": first.asset_group.sector.area.plant,
                        "technique": technique,
                        "scheduled_from": book.thermo_day,
                        "scheduled_to": book.thermo_day,
                        "status": "done",
                        "lead_analyst": analyst,
                        "standard": norma,
                    },
                )
                if order.standard_id is None:
                    # A report imported before the norma existed now cites it.
                    order.standard = norma
                    order.save(update_fields=["standard"])
                moment = datetime.combine(book.thermo_day, time(14), LIMA)
                for item, _ in machines[book.number]["machines"].values():
                    visit, created = ServiceVisit.objects.get_or_create(
                        service_order=order,
                        equipment=item,
                        defaults={
                            "company": company,
                            "visited_at": moment,
                            "instrument": instrument,
                            "availability_status": statuses["off" if summary_state == "off" else "running"],
                            "is_closed": True,
                            "closed_at": moment + timedelta(hours=1),
                            "closed_by": analyst,
                        },
                    )
                    self.made["visitas"] += int(created)
                    if item == first:
                        thermo = visit
            # Thermography first: the monthly summary shows a train's latest
            # conclusion, and on the same date the later row wins. IPSA's own
            # summary puts the vibration one in that column.
            for note in sorted(book.notes, key=lambda n: n.sheet != "thermography"):
                visit = thermo if note.sheet == "thermography" else latest
                entry_type = kinds[note.section]
                _, created = EquipmentLogEntry.objects.get_or_create(
                    company=company,
                    equipment=first,
                    entry_type=entry_type,
                    entry_date=note.day,
                    text=note.text,
                    defaults={
                        "service_visit": None if note.section == "background" else visit,
                        "author": analyst,
                        "status": "open" if entry_type == "recommendation" else "",
                    },
                )
                self.made["líneas del diario"] += int(created)
            summary = trains.get(book.number) or {}
            present = [n for n in book.notes if n.sheet == "vibration" and n.section == "present"]
            if not present and summary.get("conclusion") and latest:
                _, created = EquipmentLogEntry.objects.get_or_create(
                    company=company,
                    equipment=first,
                    entry_type="conclusion",
                    text=summary["conclusion"],
                    defaults={
                        "entry_date": latest.visited_at.astimezone(LIMA).date(),
                        "service_visit": latest,
                        "author": analyst,
                    },
                )
                self.made["líneas del diario"] += int(created)

    # --------------------------------------------------------------- images

    def _images(self, company, paths, books, machines, rounds, people) -> None:
        """The schemas, photos, spectra and thermograms pasted in each book,
        on the train's last visit of that service. 2P is not IPSA's."""
        import openpyxl

        from modules.media.infrastructure.uploads import UploadRejectedError, store_upload

        by_file = {book.filename: book for book in books}
        for path in paths:
            book = by_file[path.name]
            group = machines[book.number]["group"]
            first = next(iter(machines[book.number]["machines"].values()))[0]
            vibration = (
                ServiceVisit.objects.filter(equipment=first, service_order__code__startswith="IPSA-AV-")
                .order_by("-visited_at")
                .first()
            )
            thermography = (
                ServiceVisit.objects.filter(equipment=first, service_order__code__startswith="IPSA-TM-")
                .order_by("-visited_at")
                .first()
            )
            workbook = openpyxl.load_workbook(path)
            for sheet in workbook.worksheets:
                is_thermo = sheet.title.upper().startswith("TERMOGRAF")
                if sheet.title != "VIBRACIONES" and not is_thermo:
                    continue
                visit = thermography if is_thermo else vibration
                if visit is None:
                    continue
                for index, image in enumerate(sheet._images, start=1):
                    kind, what = _image_kind(image.anchor._from.row, is_thermo)
                    if kind is None:
                        continue
                    data = image._data()
                    extension = (getattr(image, "format", "") or "png").lower().replace("jpeg", "jpg")
                    upload = SimpleUploadedFile(
                        f"{book.code}-{sheet.title}-{index}.{extension}",
                        data,
                        content_type=f"image/{'jpeg' if extension == 'jpg' else extension}",
                    )
                    try:
                        _, created = store_upload(
                            company_id=company.id,
                            upload=upload,
                            kind=kind,
                            # The schema is the train's, shown atop its record of values (V3-14).
                            owner_type="group" if kind == "schematic" else "visit",
                            owner_id=group.id if kind == "schematic" else visit.id,
                            user=people["CB"],
                            caption=f"{what} · {book.filename}, hoja {sheet.title}, imagen {index}",
                        )
                    except UploadRejectedError as cause:
                        self.notes.append(
                            f"{book.filename}: imagen {index} de {sheet.title} rechazada ({cause})"
                        )
                        continue
                    self.made["imágenes"] += int(created)
            workbook.close()

    # --------------------------------------------------------------- status

    def _settle(self, books, machines, rounds, catalogue) -> dict:
        """Each machine's status from its train's last round, and the
        system's verdict per train for the report (AC-05)."""
        statuses = catalogue["statuses"]
        by_severity = {s.severity: s for s in statuses.values() if s.kind == "condition"}
        verdicts = {}
        for book in books:
            entry = rounds.get(book.number)
            if not entry or not entry["columns"]:
                verdicts[book.number] = (None, None, None)
                continue
            column, order = entry["columns"][-1]
            visits = entry["visits"][column.index]
            worst = 0
            for visit in visits.values():
                item = visit.equipment
                severities = [
                    s
                    for s in Reading.objects.filter(service_visit=visit, quality="ok").values_list(
                        "condition_status__severity", flat=True
                    )
                    if s is not None
                ]
                item.availability_status = statuses["off" if column.state == "off" else "running"]
                item.condition_status = by_severity.get(max(severities)) if severities else None
                item.condition_updated_at = visit.visited_at
                item.save(update_fields=["availability_status", "condition_status", "condition_updated_at"])
                worst = max([worst, *severities])
            system = (
                "off"
                if column.state == "off"
                else {10: "normal", 20: "alarm", 30: "shutdown"}.get(
                    worst, "no_access" if column.state == "no_access" else None
                )
            )
            verdicts[book.number] = (column, order.code, system)
        return verdicts

    # --------------------------------------------------------------- report

    def _report(self, books, trains, pareto, verdicts) -> str:
        label = {
            "normal": "NORMAL",
            "observation": "OBSERVACIÓN",
            "alarm": "ALARMA",
            "shutdown": "PARADA",
            "off": "APAGADO",
            "no_access": "SIN ACCESO",
            None: "—",
        }
        lines = [
            "# Importación de la planta IPSA (V3-37)",
            "",
            f"Generado el {timezone.localdate():%d/%m/%Y}. {len(books)} libros leídos; la hoja 2P no se lee.",
            "",
            "## Registros creados en esta ejecución",
            "",
        ]
        lines += [f"- {kind}: {count}" for kind, count in sorted(self.made.items()) if count] or [
            "- ninguno: ya estaba importado"
        ]

        lines += [
            "",
            "## Semáforo de vibraciones: libro, sistema y resumen (AC-05)",
            "",
            "Última columna fechada de cada libro. *Libro* es el estado escrito en esa columna; *sistema*, "
            "el peor valor calificado con los límites importados; *resumen*, la columna VIBRACIONES de "
            "`EQUIPOS - CONCLUSIONES.xlsx`.",
            "",
            "| Conjunto | Fecha | Orden | Libro | Sistema | Resumen |",
            "|---|---|---|---|---|---|",
        ]
        tallies = {"libro": Counter(), "sistema": Counter(), "resumen": Counter()}
        differences = []
        for book in books:
            column, code, system = verdicts[book.number]
            summary = (trains.get(book.number) or {}).get("vibration")
            written = column.state if column else None
            tallies["libro"][written] += 1
            tallies["sistema"][system] += 1
            tallies["resumen"][summary] += 1
            name = (trains.get(book.number) or {}).get("name") or book.header_name
            lines.append(
                f"| {book.number} · {name} | {column.day:%d/%m/%Y} | {code} | {label[written]} | "
                f"{label[system]} | {label[summary]} |"
                if column
                else f"| {book.number} · {name} | — | — | — | — | {label[summary]} |"
            )
            if len({written, system, summary}) > 1:
                differences.append((book, written, system, summary))
        lines += ["", "| Estado | Libro | Sistema | Resumen | Pareto (total) |", "|---|---|---|---|---|"]
        total = pareto.get("ESTADO", {})
        for state in ("normal", "observation", "alarm", "shutdown", "off", "no_access", None):
            row = [tallies[k][state] for k in ("libro", "sistema", "resumen")]
            if any(row) or total.get(state):
                lines.append(f"| {label[state]} | {row[0]} | {row[1]} | {row[2]} | {total.get(state, '—')} |")
        lines += [
            "",
            "Tablas de la hoja PARETO VIBRACIONAL: "
            + "; ".join(
                f"{title}: " + ", ".join(f"{label[s]} {n}" for s, n in counts.items())
                for title, counts in pareto.items()
            )
            + ".",
            "",
        ]
        last_days = Counter(verdicts[b.number][0].day for b in books if verdicts[b.number][0])
        explained = _explain(differences, trains, label, tallies, last_days, pareto)
        lines += ["### Por qué difieren", "", *explained, ""]
        thermo = Counter((trains.get(book.number) or {}).get("thermography") for book in books)
        lines += [
            "### Termografía",
            "",
            "Las hojas de termografía no traen tabla de valores, solo cabecera, textos e imágenes: sus "
            "visitas quedan sin veredicto (SIN EVALUAR o APAGADO). El resumen cuenta "
            + ", ".join(f"{'OK' if s == 'normal' else label[s]} {n}" for s, n in thermo.items())
            + ".",
            "",
        ]

        lines += ["", "## Lo que no se pudo mapear tal cual", ""]
        for book in books:
            lines += [f"- {book.filename}: {warning}" for warning in dict.fromkeys(book.warnings)]
            if book.header_state == "observation":
                lines.append(
                    f"- {book.filename}: estado OBSERVACIÓN en la cabecera; pendiente de que el cliente "
                    "diga a qué estado corresponde."
                )
            if "no opera" in plain_text((trains.get(book.number) or {}).get("recommendation", "")):
                lines.append(
                    f"- {book.filename}: el resumen dice que el equipo ya no opera; queda APAGADO, "
                    "no retirado, hasta confirmarlo."
                )
        lines += [f"- {note}" for note in dict.fromkeys(self.notes)]
        return "\n".join(lines) + "\n"


# Where each picture sits on the sheet says what it is: the banner carries
# 1A-MIG's logo, the description block the train's point schema, and below the
# values come the SKF spectra (vibration) or the FLIR captures (thermography).
HEADER_ROWS = 6
DESCRIPTION_ROWS = 19


def _image_kind(row: int, thermography: bool) -> tuple[str | None, str]:
    if row < HEADER_ROWS:
        return None, ""
    if row < DESCRIPTION_ROWS:
        return "schematic", "Esquema de puntos"
    if thermography:
        return "thermogram", "Termografía"
    return "spectrum_image", "Espectro / tendencia"


def plain_text(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def _n(value: Decimal) -> str:
    """12.1000 → 12.1, 13.0000 → 13."""
    return format(value.normalize(), "f")


RANK = {"normal": 1, "observation": 1, "alarm": 2, "shutdown": 3}


def _explain(differences, trains, label, tallies, last_days, pareto) -> list[str]:
    """Group the disagreements by their cause, from the rows themselves."""
    off_in_summary = [
        b for b, written, _, summary in differences if summary == "off" and written not in ("off", None)
    ]
    stricter = [
        b
        for b, written, system, _ in differences
        if written in RANK and system in RANK and RANK[system] > RANK[written] and written != "observation"
    ]
    milder = [
        b
        for b, written, system, _ in differences
        if written in RANK and system in RANK and RANK[system] < RANK[written]
    ]
    observed = [b for b, written, _, _ in differences if written == "observation"]
    names = lambda group: ", ".join(  # noqa: E731
        (trains.get(b.number) or {}).get("name") or b.header_name for b in group
    )
    lines = []
    if off_in_summary:
        lines.append(
            f"- El resumen marca APAGADO {len(off_in_summary)} conjuntos que su libro midió en la última "
            f"columna ({names(off_in_summary)}): el resumen cuenta el estado al cierre del 28-sep, no el "
            f"de la toma. Por eso tiene {tallies['resumen']['off']} APAGADO y los libros "
            f"{tallies['libro']['off']}."
        )
    if stricter:
        lines.append(
            f"- En {len(stricter)} conjuntos el analista escribió un estado mejor que el que dan sus propios "
            f"valores con los límites importados ({names(stricter)}): algún punto supera el límite de "
            "alarma de su norma."
        )
    if milder:
        lines.append(
            f"- En {len(milder)} el libro dice más grave que sus valores ({names(milder)}): el analista "
            "calificó por espectro o por tendencia, no solo por el valor global."
        )
    if observed:
        lines.append(
            f"- OBSERVACIÓN ({names(observed)}) no existe en el sistema: se califica por sus valores. "
            "Queda pendiente que el cliente diga a qué estado corresponde."
        )
    rounds = "; ".join(
        f"{title}: {sum(counts.values())} conjuntos" for title, counts in pareto.items() if title != "ESTADO"
    )
    columns = ", ".join(f"{count} del {day:%d/%m}" for day, count in sorted(last_days.items()))
    total = pareto.get("ESTADO", {})
    agrees = all(tallies["resumen"][state] == total.get(state, 0) for state in total)
    lines.append(
        f"- La hoja PARETO VIBRACIONAL separa rondas ({rounds}); en los libros la última columna es "
        f"{columns}. Su total {'coincide' if agrees else 'no coincide'} con la columna VIBRACIONES "
        "del resumen."
    )
    lines.append("")
    lines += [
        f"- {b.number} · {b.filename}: libro {label[w]}, sistema {label[s]}, resumen {label[r]}."
        for b, w, s, r in differences
    ]
    return lines
