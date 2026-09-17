"""Parses the customer's real RGP workbook when it is checked out next door."""

from pathlib import Path

import pytest

from modules.assets.domain.rgp import normalise_status
from modules.assets.domain.tag import extract_from_cell, parse, split_area_label

RGP = Path(__file__).resolve().parents[2].parent / "predictive-docs" / "VIBRACION 2014 AMBEV - JUNIO.xls"


class TestTagParsing:
    def test_reads_the_tag_out_of_a_two_line_cell(self):
        assert extract_from_cell("MOTOR -\nTAG:MB101001A") == "MB101001A"

    def test_guesses_the_type_from_the_prefix(self):
        assert parse("MB101001A").guessed_type == "motor"
        assert parse("B101001A").guessed_type == "pump"
        assert parse("C121001").guessed_type == "compressor"
        assert parse("R561S002").guessed_type == "gearbox"

    def test_unknown_prefix_guesses_nothing_rather_than_guessing_wrong(self):
        assert parse("ZZ999").guessed_type is None

    def test_splits_the_area_label(self):
        assert split_area_label("501 - PACKAGING CERVEZA") == ("501", "PACKAGING CERVEZA")
        assert split_area_label("551 PACKAGING REFRIGERANTES") == ("551", "PACKAGING REFRIGERANTES")


class TestStatusSplit:
    def test_condition_and_availability_do_not_share_a_field(self):
        assert normalise_status("NORMAL") == ("normal", None)
        assert normalise_status("PARADA") == ("shutdown", None)
        assert normalise_status("APAGADO") == (None, "off")
        assert normalise_status("Equipo Fuera de Servicio") == (None, "out_of_service")


@pytest.fixture(scope="module")
def rows():
    from modules.assets.infrastructure.importers.rgp_excel import read_rgp

    return list(read_rgp(RGP))


@pytest.mark.skipif(not RGP.exists(), reason="predictive-docs not checked out next to this repo")
class TestRealWorkbook:
    def test_reads_every_equipment(self, rows):
        assert len(rows) > 400

    def test_carries_the_merged_parents_down(self, rows):
        assert all(row.area_code for row in rows)
        assert all(row.sector for row in rows)

    def test_finds_the_known_pump_of_area_101(self, rows):
        pump = next(r for r in rows if r.client_tag == "B101001A")
        assert pump.area_code == "101"
        assert pump.equipment_type == "pump"
        assert pump.frequency == "bimonthly"

    def test_keeps_conclusions_and_recommendations_together(self, rows):
        with_finding = [r for r in rows if r.conclusion]
        assert len(with_finding) > 50
        assert any("Desalineamiento" in r.conclusion for r in with_finding)
