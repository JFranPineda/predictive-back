"""An alignment norma's scale as rows, and back (Q10).

Each `AlignmentTolerance` row is one band of one RPM tier: the rows sharing a
norma (or a train override) and a ceiling make that tier. A row with a status
and limits reads "up to these limits, this state"; a row with a status and
no limits is the state above them all; a row with limits and no status is a
tier saved before states existed — a plain ✓ line.
"""

from __future__ import annotations

from decimal import Decimal

from modules.alignment.domain.tolerances import DEFAULT_TIERS, Band

UNNAMED = {"status_code": None, "status_name": "", "color": "", "severity": 0}


def labels(company_id: int, language: str = "es") -> dict[str, dict]:
    from modules.thresholds.infrastructure.condition_options import condition_options

    return {option["code"]: option for option in condition_options(company_id, ["alignment"], language)}


def band_of(row, names: dict[str, dict]) -> Band:
    status = names.get(row.status.code) if row.status_id else None
    return Band(
        status_code=row.status.code if row.status_id else None,
        status_name=status["name"] if status else (row.status.name if row.status_id else ""),
        color=status["color"] if status else (row.status.color if row.status_id else ""),
        severity=status["severity"] if status else (row.status.severity if row.status_id else 0),
        parallel_mm=row.parallel_mm,
        angular_mm_per_100mm=row.angular_mm_per_100mm,
    )


def tiers_of(rows, names: dict[str, dict]) -> list[tuple[int | None, list[Band]]]:
    """The rows grouped into tiers, lowest ceiling first, the open one last."""
    tiers: dict[int | None, list[Band]] = {}
    for row in rows:
        tiers.setdefault(row.rpm_ceiling, []).append(band_of(row, names))
    return sorted(tiers.items(), key=lambda item: (item[0] is None, item[0] or 0))


def tier_for_rpm(rpm, tiers: list[tuple[int | None, list[Band]]]) -> list[Band] | None:
    """Same rule as the plain chart: the first tier whose ceiling is above the
    speed; past the last, the last (the strictest)."""
    if not tiers:
        return None
    value = float(rpm)
    for ceiling, bands in tiers:
        if ceiling is None or value < ceiling:
            return bands
    return tiers[-1][1]


def scale_for(company_id: int, group, rpm, standard, language: str = "es") -> list[Band]:
    """The train's own override tier if one covers this RPM; the chosen
    norma's (the SKF one when none was chosen); the built-in chart last."""
    from modules.alignment.domain.tolerances import SKF_NORMA_CODE
    from modules.alignment.infrastructure.models import AlignmentTolerance
    from modules.thresholds.models import ThresholdStandard

    names = labels(company_id, language)
    rows = AlignmentTolerance.objects.for_company(company_id).select_related("status")
    found = tier_for_rpm(rpm, tiers_of(rows.filter(asset_group=group), names))
    if found:
        return found
    norma = standard or ThresholdStandard.objects.for_company(company_id).filter(code=SKF_NORMA_CODE).first()
    if norma is not None:
        found = tier_for_rpm(rpm, tiers_of(rows.filter(standard=norma, asset_group__isnull=True), names))
        if found:
            return found
    for ceiling, parallel, angular in DEFAULT_TIERS:
        if ceiling is None or float(rpm) < ceiling:
            return [Band(None, "", "", 0, parallel, angular)]
    return []


def snapshot_of(bands: list[Band]) -> list[dict]:
    return [
        {
            "status_code": band.status_code,
            "status_name": band.status_name,
            "color": band.color,
            "severity": band.severity,
            "parallel_mm": _plain(band.parallel_mm),
            "angular_mm_per_100mm": _plain(band.angular_mm_per_100mm),
        }
        for band in bands
    ]


def bands_from(snapshot: list[dict]) -> list[Band]:
    return [
        Band(
            status_code=item.get("status_code"),
            status_name=item.get("status_name") or "",
            color=item.get("color") or "",
            severity=int(item.get("severity") or 0),
            parallel_mm=_decimal(item.get("parallel_mm")),
            angular_mm_per_100mm=_decimal(item.get("angular_mm_per_100mm")),
        )
        for item in snapshot or []
    ]


def _plain(value) -> str | None:
    return None if value is None else format(value.normalize(), "f")


def _decimal(value) -> Decimal | None:
    return None if value in (None, "") else Decimal(str(value))
