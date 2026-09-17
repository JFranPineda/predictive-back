"""T3 of the second round: asset_code is mandatory, client_tag is not."""

from modules.assets.domain.asset_code import generate, normalise


class TestNormalisation:
    def test_upper_cases_and_strips_separators(self):
        assert normalise("mb 101001-a") == "MB-101001-A"

    def test_drops_accents_so_codes_stay_ascii(self):
        assert normalise("Compresión N°1") == "COMPRESION-N1"


class TestGeneration:
    def test_uses_the_client_tag_when_it_is_free(self):
        # The crew recognises MB101001A; keeping it as the code is worth more
        # than any scheme we could invent.
        assert generate(area_code="101", equipment_type="motor",
                        client_tag="MB101001A", taken=[]) == "MB101001A"

    def test_falls_back_when_the_tag_is_already_taken(self):
        # EB 228 carries MB1141001B on both the motor and the pump.
        code = generate(area_code="114", equipment_type="pump",
                        client_tag="MB1141001B", taken=["MB1141001B"])
        assert code == "114-BBA-001"

    def test_generates_without_any_tag_at_all(self):
        assert generate(area_code="501", equipment_type="motor",
                        client_tag=None, taken=[]) == "501-MOT-001"

    def test_sequence_skips_what_exists(self):
        taken = ["501-MOT-001", "501-MOT-002"]
        assert generate(area_code="501", equipment_type="motor",
                        client_tag=None, taken=taken) == "501-MOT-003"

    def test_each_equipment_type_has_its_own_sequence(self):
        taken = ["101-MOT-001"]
        assert generate(area_code="101", equipment_type="pump",
                        client_tag=None, taken=taken) == "101-BBA-001"

    def test_comparison_is_case_insensitive(self):
        code = generate(area_code="101", equipment_type="motor",
                        client_tag="mb101001a", taken=["MB101001A"])
        assert code == "101-MOT-001"
