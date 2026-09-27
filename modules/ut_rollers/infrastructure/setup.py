"""What installing UT-en-rodillos from /settings/modules creates.

Run by the module installer on install and on every upgrade, so everything is
get-or-create: a company that already edited its limits keeps them.
"""

from __future__ import annotations

from datetime import date

from modules.measurements.domain.magnitude_order import display_order_for
from modules.ut_rollers.domain.rollers import (
    DEFAULT_BANDS,
    LABELS,
    MAGNITUDE,
    NORMA_CODE,
    NORMA_NAME,
    NORMA_SOURCE,
    POINTS,
    TECHNIQUE,
)

KIND = "rollers"


def install() -> None:
    from modules.core.models import Company
    from modules.measurements.models import Magnitude, Technique, Unit

    technique, _ = Technique.objects.update_or_create(
        code=TECHNIQUE,
        defaults={
            "name": "END · UT en rodillos",
            "module_code": "ut_rollers",
            "family": "ndt",
            "headline_magnitude": MAGNITUDE,
            "translations": {"name": {"es": "END · UT en rodillos", "en": "NDT · UT on rollers"}},
        },
    )
    Magnitude.objects.update_or_create(
        code=MAGNITUDE,
        defaults={
            "technique": technique,
            "name": "Espesor de pared del rodillo",
            "default_unit": Unit.objects.get(code="mm"),
            "default_aggregation": "min",
            "decimals": 2,
            "higher_is_worse": False,
            "per_axis": False,
            "short_code": "P{n}",
            "display_order": display_order_for(MAGNITUDE),
            "translations": {
                "name": {"es": "Espesor de pared del rodillo", "en": "Roller wall thickness"}
            },
        },
    )
    for company in Company.objects.all():
        _profile(company, technique)
        _limits(company)
        _norma(company, technique)
        _kind(company)


def _profile(company, technique) -> None:
    """The plant's own severity scale, named the way the UT order names it;
    availability options are the ones its sister service already offers."""
    from modules.thresholds.models import Status, TechniqueStatusOption, TechniqueStatusProfile

    profile, _ = TechniqueStatusProfile.objects.get_or_create(company=company, technique=technique)
    statuses = {row.code: row for row in Status.objects.for_company(company.id)}
    order = 0
    if "off" in statuses:
        TechniqueStatusOption.objects.get_or_create(
            profile=profile, status=statuses["off"], defaults={"order": order}
        )
    for code, label in LABELS.items():
        order += 1
        if code in statuses:
            TechniqueStatusOption.objects.update_or_create(
                profile=profile, status=statuses[code],
                defaults={"order": order, "display_name": label},
            )


def _limits(company) -> None:
    from modules.thresholds.models import Status, ThresholdBand, ThresholdSet

    if ThresholdSet.objects.for_company(company.id).filter(magnitude_code=MAGNITUDE).exists():
        return
    statuses = {row.code: row for row in Status.objects.for_company(company.id).filter(kind="condition")}
    if not all(band.status_code in statuses for band in DEFAULT_BANDS):
        return
    threshold_set = ThresholdSet.objects.create(
        company=company, scope="global", magnitude_code=MAGNITUDE, unit_code="mm",
        aggregation="min", valid_from=date(2020, 1, 1),
        rationale=(
            "Inferido de la orden 14778 (IPSA, secadores): MEDIO con el espesor mínimo ≤ 8,00 mm. "
            "CRÍTICO bajo 6,14 mm (75 % de la pared de 8,18 mm del tubo de 8\" SCH 40) es un supuesto "
            "pendiente de confirmar con el cliente (Q15)."
        ),
    )
    for order, band in enumerate(DEFAULT_BANDS):
        ThresholdBand.objects.create(
            threshold_set=threshold_set, status=statuses[band.status_code],
            min_value=band.min_value, max_value=band.max_value, order=order,
        )


def _norma(company, technique) -> None:
    """Q15: the thickness scale is a norma of UT, so Normas shows it and edits
    it band by band — from A to B, state W — and an order can name it or
    another UT norma. The company's existing global scale becomes its scale."""
    from modules.thresholds.models import ThresholdSet, ThresholdStandard

    norma, _ = ThresholdStandard.objects.get_or_create(
        company=company, code=NORMA_CODE,
        defaults={"name": NORMA_NAME, "source": NORMA_SOURCE, "is_builtin": True,
                  "translations": {"name": {"es": NORMA_NAME}}},
    )
    norma.techniques.add(technique)
    ThresholdSet.objects.for_company(company.id).filter(
        magnitude_code=MAGNITUDE, scope="global", standard__isnull=True, machine_class__isnull=True
    ).update(standard=norma)


def _kind(company) -> None:
    """A dryer group is a train of identical rollers: the kind declares one
    roller's six points, and each roller added to a group gets them."""
    from modules.assets.models import AssetGroupComponent, AssetGroupKind, PointTemplate

    kind, created = AssetGroupKind.objects.get_or_create(
        company=company, code=KIND,
        defaults={
            "name": "Rodillos",
            "description": "Grupo de rodillos o polines: seis puntos de espesor por rodillo",
            "is_builtin": True,
            "translations": {"name": {"es": "Rodillos", "en": "Rollers"}},
        },
    )
    if not created:
        return
    component = AssetGroupComponent.objects.create(
        kind=kind, order=0, label="RODILLO", equipment_type="roller", position="driven",
        point_count=POINTS,
    )
    for number in range(1, POINTS + 1):
        PointTemplate.objects.create(
            kind=kind, component=component, number=number, axis="N", side="custom",
            point_type="bearing", magnitudes=[MAGNITUDE], order=number,
        )
