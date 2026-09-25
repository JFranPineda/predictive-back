"""The train kinds every company starts with, and how each one is measured.

Straight from the inspection reports and the September 2026 review with the
customer: the numbering runs across the whole train, and each machine
contributes as many points as it is actually read on. A motor-compressor is
read on six points (the Ingersoll Rand: six envelopes, eighteen velocities),
a motor-gearbox on eight, and the eight-point turbine train reads its turbine
on points whose side the customer calls "otro".

This is the single source of the factory layout: the demo seed builds from it
and the repair migration restores it.
"""

from __future__ import annotations

from dataclasses import dataclass

from modules.assets.domain.point_layout import ComponentSpec


@dataclass(frozen=True)
class KindBlueprint:
    code: str
    name: str
    name_en: str
    components: tuple[ComponentSpec, ...]

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(component.label for component in self.components)


def _motor() -> ComponentSpec:
    return ComponentSpec("MOTOR", 2, "driver", "motor")


BUILTIN_KINDS: tuple[KindBlueprint, ...] = (
    KindBlueprint("motor_pump", "Motor-Bomba", "Motor-Pump",
                  (_motor(), ComponentSpec("BOMBA", 2, "driven", "pump"))),
    KindBlueprint("motor_compressor", "Motor-Compresor", "Motor-Compressor",
                  (_motor(), ComponentSpec("COMPRESOR", 4, "driven", "compressor"))),
    KindBlueprint("motor_turbine", "Motor-Turbina", "Motor-Turbine",
                  (_motor(), ComponentSpec("TURBINA", 2, "driven", "turbine"))),
    KindBlueprint("motor_turbine_8", "Motor-Turbina (8 puntos)", "Motor-Turbine (8 points)",
                  (_motor(), ComponentSpec("TURBINA", 6, "driven", "turbine", ("custom",) * 6))),
    KindBlueprint("motor_gearbox", "Motor-Reductor", "Motor-Gearbox",
                  (_motor(), ComponentSpec("REDUCTOR", 6, "driven", "gearbox"))),
    KindBlueprint("motor_gearbox_bearings", "Motor-Reductor con chumaceras",
                  "Motor-Gearbox with bearing housings",
                  (_motor(), ComponentSpec("REDUCTOR", 4, "driven", "gearbox"),
                   ComponentSpec("CHUMACERA LADO MANDO", 2, "driven", "bearing_housing"),
                   ComponentSpec("CHUMACERA LADO TRANSMISIÓN", 2, "driven", "bearing_housing"))),
    KindBlueprint("bearing_gearbox", "Chumacera-Reductor", "Bearing housing-Gearbox",
                  (ComponentSpec("CHUMACERA", 1, "driver", "bearing_housing"),
                   ComponentSpec("REDUCTOR", 5, "driven", "gearbox"))),
    KindBlueprint("motor_fan", "Motor-Ventilador", "Motor-Fan",
                  (_motor(), ComponentSpec("VENTILADOR", 2, "driven", "fan"))),
    KindBlueprint("motor_blower", "Motor-Soplador", "Motor-Blower",
                  (_motor(), ComponentSpec("SOPLADOR", 2, "driven", "blower"))),
    KindBlueprint("standalone", "Equipo aislado", "Standalone equipment",
                  (ComponentSpec("EQUIPO", 2, "driver", "other"),)),
)


def blueprint_for(code: str) -> KindBlueprint | None:
    return next((kind for kind in BUILTIN_KINDS if kind.code == code), None)


def was_repurposed(blueprint: KindBlueprint, current_labels: tuple[str, ...]) -> bool:
    """A built-in kind whose machines were renamed now describes some other
    train. Restoring it in place would throw that work away."""
    return bool(current_labels) and current_labels != blueprint.labels
