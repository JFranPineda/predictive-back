"""Built-in train kinds back to their factory layout (V3-03, V3-12).

Three things had drifted in the customer's database:

- "Equipo aislado", used by 104 trains, had been rewritten into the MP3
  transmission line (a motor plus 22 bearing housings) and left with no point
  template at all. That rewrite is kept as a kind of its own before the
  built-in one is restored.
- Components declared one number of points and their template carried another
  (the compressor: 2 declared, 4 in the template).
- The factory layout itself changed with the September review: a compressor
  is read on six points with an envelope on each, a gearbox train on eight,
  and there is an eight-point turbine train.

Existing trains keep their points: a template is only applied when a train is
created or when someone presses "Aplicar plantilla".
"""

import re

from django.db import migrations

from modules.assets.domain.builtin_kinds import BUILTIN_KINDS, was_repurposed
from modules.assets.domain.point_layout import ComponentSpec
from modules.assets.infrastructure.kind_layouts import write_layout


def restore_builtin_kinds(apps, schema_editor):
    alias = schema_editor.connection.alias
    Company = apps.get_model("core", "Company")
    Kind = apps.get_model("assets", "AssetGroupKind")
    Component = apps.get_model("assets", "AssetGroupComponent")
    Template = apps.get_model("assets", "PointTemplate")
    models = {"component_model": Component, "template_model": Template, "using": alias}

    for company in Company.objects.using(alias).all():
        kinds = Kind.objects.using(alias).filter(company=company)
        if not kinds.exists():
            continue  # a fresh database: the seed builds the kinds itself
        for blueprint in BUILTIN_KINDS:
            kind = kinds.filter(code=blueprint.code).first()
            if kind is None:
                kind = Kind.objects.using(alias).create(company=company, code=blueprint.code,
                                                        name=blueprint.name, is_builtin=True)
            else:
                current = list(Component.objects.using(alias).filter(kind=kind).order_by("order", "id"))
                if was_repurposed(blueprint, tuple(c.label for c in current)):
                    _keep_as_custom(kind, current, Kind, models)
            kind.name = blueprint.name
            kind.is_builtin = True
            kind.translations = {"name": {"es": blueprint.name, "en": blueprint.name_en}}
            kind.save(using=alias)
            write_layout(kind, blueprint.components, **models)


def _keep_as_custom(kind, components, Kind, models):
    alias = models["using"]
    name = " + ".join(component.label for component in components)
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:50] or "custom_kind"
    code, suffix = base, 2
    while Kind.objects.using(alias).filter(company_id=kind.company_id, code=code).exists():
        code, suffix = f"{base}_{suffix}", suffix + 1
    clone = Kind.objects.using(alias).create(
        company_id=kind.company_id, code=code, name=name, description=kind.description,
        is_builtin=False, translations={"name": {"es": name}},
    )
    write_layout(
        clone,
        [ComponentSpec(c.label, c.point_count, c.position, c.equipment_type) for c in components],
        **models,
    )


class Migration(migrations.Migration):
    dependencies = [("assets", "0007_train_component_layout"), ("core", "0001_initial")]

    operations = [migrations.RunPython(restore_builtin_kinds, migrations.RunPython.noop)]
