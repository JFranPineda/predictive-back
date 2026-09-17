"""T7: the plant traffic light, built from the areas of the real RGP."""

from modules.summaries.domain.rollup import (
    EquipmentStatus,
    by_technique,
    roll_up,
    worst_of,
)
from modules.thresholds.domain.defaults import ALARM, OFF, OPERATIONAL, RETIRED, SHUTDOWN


def equipment(equipment_id, condition=None, availability=None, area=101, sector=1,
              group=1, technique="vibration"):
    return EquipmentStatus(
        equipment_id=equipment_id,
        name=f"EQ-{equipment_id}",
        area_id=area,
        area_label=f"{area} - ÁREA",
        sector_id=sector,
        sector_label=f"SECTOR {sector}",
        asset_group_id=group,
        asset_group_label=f"CONJUNTO {group}",
        technique_code=technique,
        condition=condition,
        availability=availability,
    )


class TestEffectiveStatus:
    def test_condition_shows_when_the_equipment_could_be_measured(self):
        assert equipment(1, condition=ALARM).effective is ALARM

    def test_a_stale_condition_never_survives_an_unmeasurable_state(self):
        row = equipment(1, condition=OPERATIONAL, availability=OFF)
        assert row.effective is OFF
        assert not row.counts_for_health

    def test_retired_equipment_does_not_count_as_healthy(self):
        assert equipment(1, availability=RETIRED).effective is RETIRED

    def test_never_evaluated_is_its_own_state(self):
        assert equipment(1).effective.code == "not_evaluated"


class TestWorstWins:
    def test_one_shutdown_colours_the_whole_area(self):
        rows = [equipment(i, condition=OPERATIONAL) for i in range(9)]
        rows.append(equipment(9, condition=SHUTDOWN))
        [area] = roll_up(rows, ("area",))
        assert area.worst is SHUTDOWN
        assert area.color == SHUTDOWN.color

    def test_an_area_with_no_measurement_is_not_green(self):
        rows = [equipment(i, availability=OFF) for i in range(4)]
        [area] = roll_up(rows, ("area",))
        assert area.worst.code == "not_evaluated"
        assert area.evaluated == 0

    def test_worst_of_ignores_availability(self):
        assert worst_of([OPERATIONAL, OFF, ALARM]) is ALARM
        assert worst_of([OFF, RETIRED]).code == "not_evaluated"


class TestCoverage:
    def test_coverage_exposes_the_equipment_nobody_measured(self):
        rows = [equipment(1, condition=OPERATIONAL), equipment(2, condition=OPERATIONAL),
                equipment(3, availability=OFF), equipment(4)]
        [area] = roll_up(rows, ("area",))
        assert area.total == 4
        assert area.evaluated == 2
        assert area.coverage == 0.5

    def test_counts_break_down_by_status(self):
        rows = [equipment(1, condition=OPERATIONAL), equipment(2, condition=ALARM),
                equipment(3, condition=ALARM), equipment(4, availability=OFF)]
        [area] = roll_up(rows, ("area",))
        assert area.count_of("alarm") == 2
        assert area.count_of("operational") == 1
        assert area.count_of("off") == 1

    def test_worst_status_is_listed_first(self):
        rows = [equipment(1, condition=OPERATIONAL), equipment(2, condition=SHUTDOWN)]
        [area] = roll_up(rows, ("area",))
        assert area.counts[0].status is SHUTDOWN


class TestHierarchy:
    def test_rolls_through_area_sector_and_group(self):
        rows = [
            equipment(1, condition=OPERATIONAL, area=101, sector=1, group=1),
            equipment(2, condition=SHUTDOWN, area=101, sector=2, group=2),
            equipment(3, condition=OPERATIONAL, area=131, sector=3, group=3),
        ]
        nodes = roll_up(rows)
        assert [n.label for n in nodes] == ["101 - ÁREA", "131 - ÁREA"]
        area_101 = nodes[0]
        assert area_101.worst is SHUTDOWN
        assert len(area_101.children) == 2
        # Inside the area, the bad sector is surfaced first.
        assert area_101.children[0].worst is SHUTDOWN
        assert area_101.children[0].children[0].level == "asset_group"

    def test_areas_are_ordered_worst_first(self):
        rows = [
            equipment(1, condition=OPERATIONAL, area=101),
            equipment(2, condition=ALARM, area=121),
            equipment(3, condition=SHUTDOWN, area=131),
        ]
        assert [n.label[:3] for n in roll_up(rows, ("area",))] == ["131", "121", "101"]


class TestPerTechnique:
    def test_one_traffic_light_per_service_type(self):
        rows = [
            equipment(1, condition=ALARM, technique="vibration"),
            equipment(1, condition=OPERATIONAL, technique="thermography"),
        ]
        summaries = by_technique(rows)
        assert set(summaries) == {"vibration", "thermography"}
        assert summaries["vibration"][0].worst is ALARM
        assert summaries["thermography"][0].worst is OPERATIONAL

    def test_techniques_are_not_merged_into_one_verdict(self):
        # The same pump: bad on vibration, fine on thermography. Merging would
        # hide exactly the finding the report exists for.
        rows = [
            equipment(7, condition=SHUTDOWN, technique="vibration"),
            equipment(7, condition=OPERATIONAL, technique="thermography"),
        ]
        summaries = by_technique(rows)
        assert summaries["vibration"][0].color != summaries["thermography"][0].color
