"""A norma as the Normas screen shows it: what it judges, its classes, and
its scale — the bands it grades each magnitude with (Q9, Q10)."""

from __future__ import annotations


def standard_payload(row, language: str) -> dict:
    from modules.thresholds.infrastructure.condition_options import condition_options

    techniques = [t.code for t in row.techniques.all()]
    options = condition_options(row.company_id, techniques, language)
    return {
        "id": row.id,
        "code": row.code,
        "name": row.translated("name", language),
        "names": row.translations.get("name") or {},
        "source": row.source,
        "description": row.description,
        "is_builtin": row.is_builtin,
        "is_active": row.is_active,
        "techniques": [
            {"code": t.code, "name": t.translated("name", language)} for t in row.techniques.all()
        ],
        "machine_classes": [
            {"id": mc.id, "code": mc.code, "name": mc.name, "description": mc.description}
            for mc in row.machine_classes.all()
        ],
        "set_count": row.sets.count(),
        "scale": scale_of(row, language, {option["code"]: option["name"] for option in options}),
        # The states a band of this norma may name, as its service calls them.
        "status_options": options,
    }


def scale_of(row, language: str, status_names: dict[str, str] | None = None) -> list[dict]:
    """The norma's own global sets, one per magnitude. Sets for one machine
    class stay in Umbrales: they are the class tables, not the scale."""
    from modules.measurements.models import Magnitude

    sets = (
        row.sets.filter(is_active=True, scope="global", machine_class__isnull=True)
        .prefetch_related("bands__status")
        .order_by("magnitude_code", "-valid_from", "-version")
    )
    names = {m.code: m.translated("name", language) for m in Magnitude.objects.all()}
    seen: set[tuple[str, str]] = set()
    scale = []
    for threshold_set in sets:
        key = (threshold_set.magnitude_code, threshold_set.aggregation)
        if key in seen:
            continue
        seen.add(key)
        scale.append({
            "set_id": threshold_set.id,
            "magnitude_code": threshold_set.magnitude_code,
            "magnitude_name": names.get(threshold_set.magnitude_code, threshold_set.magnitude_code),
            "unit_code": threshold_set.unit_code,
            "aggregation": threshold_set.aggregation,
            "bands": [
                {
                    "status_code": band.status.code,
                    "status_name": (status_names or {}).get(band.status.code)
                    or band.status.translated("name", language),
                    "color": band.status.color,
                    "min_value": _plain(band.min_value),
                    "max_value": _plain(band.max_value),
                }
                for band in threshold_set.bands.all()
            ],
        })
    return scale


def _plain(value) -> str | None:
    """82.0000 → "82", not "8.2E+1": normalize alone writes 10 as 1E+1."""
    return None if value is None else format(value.normalize(), "f")
