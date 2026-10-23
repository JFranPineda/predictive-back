"""Lays the base catalogue into the current tenant's database (v4 Phase 6).

Get-or-create throughout: the data migrations already write some of these
rows (techniques, a few magnitudes), a customer may have edited others, and a
second run creates nothing. What already exists is kept as it is.
"""

from __future__ import annotations

import importlib
from collections import Counter
from dataclasses import dataclass, field

from modules.core.domain import base_catalogue as base


@dataclass
class Catalogue:
    statuses: dict = field(default_factory=dict)
    units: dict = field(default_factory=dict)
    techniques: dict = field(default_factory=dict)
    magnitudes: dict = field(default_factory=dict)
    standards: dict = field(default_factory=dict)
    kinds: dict = field(default_factory=dict)
    # What this run created, by the names the import report uses.
    made: Counter = field(default_factory=Counter)


def lay_base_catalogue(company, *, using: str) -> Catalogue:
    catalogue = Catalogue()
    _statuses(company, catalogue)
    _measurements(catalogue)
    _standards(company, catalogue)
    _profiles(company, catalogue)
    _faults(company, catalogue)
    _operating_parameters(company, catalogue)
    _kinds(company, catalogue, using)
    return catalogue


def lay_roles(company) -> tuple[dict, Counter]:
    """The base roles, with the permissions the installed modules declare.
    Run after the modules are installed: a role laid before has nothing to
    grant. A role that exists keeps the permissions it has."""
    from modules.security.models import Permission, Role

    active = {p.code: p for p in Permission.objects.filter(is_active=True)}
    roles, made = {}, Counter()
    for code, granted in base.ROLES.items():
        role, created = Role.objects.get_or_create(
            company=company, code=code, defaults={"name": code.replace("_", " ").title()}
        )
        if created:
            made["roles"] += 1
            role.permissions.set(
                active.values() if granted == ["*"] else [active[p] for p in granted if p in active]
            )
        roles[code] = role
    return roles, made


def _get(catalogue: Catalogue, model, tally: str, defaults: dict | None = None, **lookup):
    row, created = model.objects.get_or_create(defaults=defaults or {}, **lookup)
    if created:
        catalogue.made[tally] += 1
    return row


def _statuses(company, catalogue: Catalogue) -> None:
    from modules.thresholds.domain.defaults import ALL_STATUSES, TRANSLATIONS
    from modules.thresholds.models import Status

    for status in ALL_STATUSES:
        catalogue.statuses[status.code] = _get(
            catalogue, Status, "estados", company=company, code=status.code,
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


def _measurements(catalogue: Catalogue) -> None:
    from modules.measurements.domain.acceleration import ACCELERATION
    from modules.measurements.domain.families import family_for
    from modules.measurements.domain.magnitude_order import display_order_for, in_record_by_default
    from modules.measurements.domain.thermography import IR_TMAX_SPEC
    from modules.measurements.models import Magnitude, Technique, Unit

    # What the migration marks on magnitudes that already existed; a fresh
    # database needs the same, or its magnitudes differ from every other's.
    per_bearing = importlib.import_module(
        "modules.measurements.migrations.0005_magnitude_per_axis"
    ).PER_BEARING

    for code, name, translations in base.UNITS:
        catalogue.units[code] = _get(
            catalogue, Unit, "unidades", code=code,
            defaults={"name": name, "translations": {"name": translations}},
        )
    for code, name_es, name_en, module in base.TECHNIQUES:
        catalogue.techniques[code] = _get(
            catalogue, Technique, "técnicas", code=code,
            defaults={
                "name": name_es,
                "module_code": module,
                "family": family_for(code),
                "headline_magnitude": base.HEADLINES.get(code, ""),
                "close_requirement": "plan_required" if code in base.PLAN_REQUIRED else "",
                "evidence_only": code in base.EVIDENCE_ONLY,
                "translations": {"name": {"es": name_es, "en": name_en}},
            },
        )

    rows = [(*row, base.MAGNITUDE_OPTIONS.get(row[0], {})) for row in base.MAGNITUDES]
    for spec in (ACCELERATION, IR_TMAX_SPEC):
        rows.append((
            spec.code, spec.technique, spec.name_es, spec.name_en, spec.unit, spec.aggregation,
            spec.decimals,
            {
                "per_axis": spec.per_axis,
                "higher_is_worse": spec.higher_is_worse,
                "short_code": getattr(spec, "short_code", ""),
                "template_only": getattr(spec, "template_only", False),
            },
        ))
    for code, technique, name_es, name_en, unit, aggregation, decimals, options in rows:
        defaults = {
            "technique": catalogue.techniques[technique],
            "name": name_es,
            "default_unit": catalogue.units[unit],
            "default_aggregation": aggregation,
            "decimals": decimals,
            "display_order": display_order_for(code),
            "in_record": in_record_by_default(code),
            "translations": {"name": {"es": name_es, "en": name_en}},
            "per_axis": code not in per_bearing,
            "short_code": per_bearing.get(code, ""),
        }
        defaults.update({k: v for k, v in options.items() if v not in ("", None)})
        catalogue.magnitudes[code] = _get(catalogue, Magnitude, "magnitudes", code=code, defaults=defaults)


def _standards(company, catalogue: Catalogue) -> None:
    from modules.thresholds.domain.defaults import STANDARDS
    from modules.thresholds.models import MachineClass, ThresholdStandard

    for standard in STANDARDS:
        row = _get(
            catalogue, ThresholdStandard, "normas", company=company, code=standard.code,
            defaults={"name": standard.name, "source": standard.source, "is_builtin": True},
        )
        # A standard judges the service type it was written for.
        row.techniques.add(
            *[catalogue.techniques[c] for c in standard.techniques if c in catalogue.techniques]
        )
        for order, machine_class in enumerate(standard.machine_classes):
            _get(
                catalogue, MachineClass, "clases", standard=row, code=machine_class.code,
                defaults={
                    "name": machine_class.name,
                    "description": machine_class.description,
                    "order": order,
                    "power_min_kw": machine_class.power_min_kw,
                    "power_max_kw": machine_class.power_max_kw,
                    "mounting": machine_class.mounting.value,
                },
            )
        catalogue.standards[standard.code] = row


def _profiles(company, catalogue: Catalogue) -> None:
    from modules.thresholds.domain.defaults import PROFILES
    from modules.thresholds.models import TechniqueStatusOption, TechniqueStatusProfile

    for profile in PROFILES:
        technique = catalogue.techniques.get(profile.technique_code)
        if technique is None:
            continue
        row = _get(catalogue, TechniqueStatusProfile, "perfiles", company=company, technique=technique)
        for order, status in enumerate(profile.options):
            _get(
                catalogue, TechniqueStatusOption, "perfiles", profile=row,
                status=catalogue.statuses[status.code], defaults={"order": order},
            )


def _faults(company, catalogue: Catalogue) -> None:
    from modules.diagnostics.domain.catalogue import ALL_FAULTS
    from modules.diagnostics.models import FaultMode

    for fault in ALL_FAULTS:
        _get(
            catalogue, FaultMode, "modos de falla", company=company, code=fault.code,
            defaults={
                "name": fault.name_es,
                "technique_code": fault.technique,
                "typical_signature": fault.signature,
                "iso_reference": fault.reference,
                "translations": {"name": {"es": fault.name_es, "en": fault.name_en}},
            },
        )


def _operating_parameters(company, catalogue: Catalogue) -> None:
    from modules.operating_data.models import OperatingParameter

    for order, (code, es, en, unit, technique, applies, cumulative) in enumerate(base.OPERATING_PARAMETERS):
        _get(
            catalogue, OperatingParameter, "parámetros", company=company, code=code,
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


def _kinds(company, catalogue: Catalogue, using: str) -> None:
    """The train taxonomy and the point layout each one measures."""
    from modules.assets.domain.builtin_kinds import BUILTIN_KINDS
    from modules.assets.infrastructure.kind_layouts import write_layout
    from modules.assets.models import AssetGroupComponent, AssetGroupKind, PointTemplate

    for blueprint in BUILTIN_KINDS:
        kind, created = AssetGroupKind.objects.get_or_create(
            company=company, code=blueprint.code,
            defaults={
                "name": blueprint.name,
                "is_builtin": True,
                "translations": {"name": {"es": blueprint.name, "en": blueprint.name_en}},
            },
        )
        if created:
            catalogue.made["tipos de conjunto"] += 1
            # The layout helper defaults to `default`, the control plane.
            write_layout(
                kind, blueprint.components,
                component_model=AssetGroupComponent, template_model=PointTemplate, using=using,
            )
        catalogue.kinds[blueprint.code] = kind
