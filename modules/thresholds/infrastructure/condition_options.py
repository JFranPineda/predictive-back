"""The condition states a norma may name, as its technique calls them.

A band's state is one of the company's condition statuses; the technique's
status profile may rename it (UT's "Medio" is the plant's Alarma). The Normas
screen offers these names when a scale is edited (Q10, Q15), and modules that
grade with their own scales (alignment) print them.
"""

from __future__ import annotations

from collections.abc import Iterable


def condition_options(
    company_id: int, technique_codes: Iterable[str] = (), language: str = "es"
) -> list[dict]:
    from modules.thresholds.infrastructure.models import Status, TechniqueStatusOption

    renamed: dict[str, str] = {}
    for code in technique_codes:
        options = TechniqueStatusOption.objects.filter(
            profile__company_id=company_id, profile__technique__code=code
        ).select_related("status")
        for option in options:
            if option.display_name and option.status.code not in renamed:
                renamed[option.status.code] = option.display_name
        if renamed:
            break
    statuses = Status.objects.for_company(company_id).filter(kind="condition").order_by("severity", "id")
    return [
        {
            "code": row.code,
            "name": renamed.get(row.code) or row.translated("name", language),
            "color": row.color,
            "severity": row.severity,
        }
        for row in statuses
    ]
