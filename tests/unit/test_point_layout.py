"""The point layout of a train, taken from the real inspection reports.

`docs/vibration/reports` holds three shapes and none of them is uniform:
2+4 (report 0021), 2+4+2+2 (report 0023) and 1+5 (report 0026). The numbering
runs across the whole train in every one of them.
"""

from modules.assets.domain.point_layout import (
    ComponentSpec,
    next_number,
    plan_layout,
)


def numbers_of(rows, component_label):
    return sorted({row.number for row in rows if row.component_label == component_label})


def test_motor_two_points_gearbox_four_numbers_run_across_the_train():
    rows = plan_layout([
        ComponentSpec(label="MOTOR", point_count=2, position="driver", equipment_type="motor"),
        ComponentSpec(label="REDUCTOR", point_count=4, equipment_type="gearbox"),
    ])

    assert numbers_of(rows, "MOTOR") == [1, 2]
    assert numbers_of(rows, "REDUCTOR") == [3, 4, 5, 6]


def test_press_train_numbers_ten_points_over_four_components():
    rows = plan_layout([
        ComponentSpec(label="MOTOR", point_count=2, position="driver", equipment_type="motor"),
        ComponentSpec(label="REDUCTOR", point_count=4, equipment_type="gearbox"),
        ComponentSpec(
            label="CHUMACERA LADO MANDO", point_count=2, equipment_type="bearing_housing",
            sides=("lower", "upper"),
        ),
        ComponentSpec(
            label="CHUMACERA LADO TRANSMISIÓN", point_count=2,
            equipment_type="bearing_housing", sides=("lower", "upper"),
        ),
    ])

    assert numbers_of(rows, "CHUMACERA LADO MANDO") == [7, 8]
    assert numbers_of(rows, "CHUMACERA LADO TRANSMISIÓN") == [9, 10]
    # Two housings of the same kind must not share a point: the code the
    # analyst writes ("HV-9") carries no component.
    assert len({(row.number, row.axis) for row in rows}) == len(rows)


def test_dryer_group_has_one_bearing_housing_and_a_five_point_gearbox():
    rows = plan_layout([
        ComponentSpec(
            label="CHUMACERA", point_count=1, position="driver",
            equipment_type="bearing_housing",
        ),
        ComponentSpec(label="REDUCTOR", point_count=5, equipment_type="gearbox"),
    ])

    assert numbers_of(rows, "CHUMACERA") == [1]
    assert numbers_of(rows, "REDUCTOR") == [2, 3, 4, 5, 6]


def test_bearing_housing_keeps_the_side_the_sheet_prints():
    rows = plan_layout([
        ComponentSpec(
            label="CHUMACERA LADO MANDO", point_count=2,
            equipment_type="bearing_housing", sides=("lower", "upper"),
        ),
    ])

    assert {row.side for row in rows if row.number == 1} == {"lower"}
    assert {row.side for row in rows if row.number == 2} == {"upper"}


def test_every_point_is_read_on_three_axes_with_envelope_on_the_horizontal():
    rows = plan_layout([ComponentSpec(label="MOTOR", point_count=1, position="driver")])

    assert sorted(row.axis for row in rows) == ["A", "H", "V"]
    horizontal = next(row for row in rows if row.axis == "H")
    assert horizontal.magnitudes == ["vel_rms", "env_accel", "temp"]


def test_numbering_continues_from_what_the_train_already_has():
    assert next_number([1, 2, 3, 4, 5, 6]) == 7
    assert next_number([]) == 1
