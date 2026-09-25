"""Writing a kind's components and point template from a blueprint.

Shared by the demo seed and the repair migration, so both take the model
classes as arguments: a migration must use its historical models.
"""

from __future__ import annotations

from collections.abc import Sequence

from modules.assets.domain.point_layout import ComponentSpec, plan_layout


def write_layout(kind, components: Sequence[ComponentSpec], *, component_model, template_model,
                 using: str = "default") -> None:
    """Components are updated in place, by order: equipment points at them,
    and a delete-and-recreate would cut every machine loose from its slot."""
    existing = list(component_model.objects.using(using).filter(kind=kind).order_by("order", "id"))
    written = []
    for index, spec in enumerate(components):
        row = existing[index] if index < len(existing) else component_model(kind=kind)
        row.order = index
        row.label = spec.label
        row.equipment_type = spec.equipment_type
        row.position = spec.position
        row.point_count = spec.point_count
        row.save(using=using)
        written.append(row)
    for stale in existing[len(components):]:
        stale.delete()

    by_label = {row.label: row for row in written}
    template_model.objects.using(using).filter(kind=kind).delete()
    template_model.objects.using(using).bulk_create([
        template_model(
            kind=kind, component=by_label[point.component_label], number=point.number,
            axis=point.axis, side=point.side, magnitudes=point.magnitudes, order=point.order,
        )
        for point in plan_layout(components)
    ])
