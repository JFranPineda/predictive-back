"""The instrument import seam: manual entry today, CSV parsers later."""

from datetime import datetime
from decimal import Decimal
from io import BytesIO

import pytest

from modules.measurements.domain.importing import (
    DuplicateImporter,
    ImportedReading,
    ImporterRegistry,
    ImportResult,
    NoImporterForFile,
    ReadingImporter,
)


class FakeImporter:
    def __init__(self, code: str, name: str, extensions: tuple[str, ...]):
        self.code = code
        self.name = name
        self.extensions = extensions

    def supports(self, filename: str) -> bool:
        return filename.lower().endswith(self.extensions)

    def parse(self, stream) -> ImportResult:
        return ImportResult(
            readings=(
                ImportedReading(
                    point_label="1H", magnitude_code="vel_rms", value=Decimal("4.6"),
                    unit_code="mm/s", aggregation="rms",
                    taken_at=datetime(2013, 12, 17, 9, 30), equipment_tag="MB1141001B",
                ),
            ),
            source_instrument=self.code,
        )


SEMAPI = FakeImporter("semapi_dsp_mx300", "SEMAPI DSP Logger MX300", (".csv",))
SKF = FakeImporter("skf_microlog_gx", "SKF Microlog GX", (".xls", ".xlsx"))


class TestRegistry:
    def test_satisfies_the_port(self):
        assert isinstance(SEMAPI, ReadingImporter)

    def test_picks_the_importer_by_extension(self):
        registry = ImporterRegistry()
        registry.register(SEMAPI)
        registry.register(SKF)
        assert registry.for_file("ruta_junio.csv") is SEMAPI
        assert registry.for_file("EB228.XLSX") is SKF

    def test_an_unknown_file_is_refused_rather_than_guessed(self):
        registry = ImporterRegistry()
        registry.register(SEMAPI)
        with pytest.raises(NoImporterForFile):
            registry.for_file("ruta.dat")

    def test_registering_the_same_instrument_twice_is_a_bug(self):
        registry = ImporterRegistry()
        registry.register(SEMAPI)
        with pytest.raises(DuplicateImporter):
            registry.register(SEMAPI)

    def test_lists_what_the_user_can_choose_from(self):
        registry = ImporterRegistry()
        registry.register(SKF)
        registry.register(SEMAPI)
        assert [i.name for i in registry.available()] == [
            "SEMAPI DSP Logger MX300", "SKF Microlog GX",
        ]

    def test_an_explicit_choice_does_not_need_the_filename(self):
        registry = ImporterRegistry()
        registry.register(SEMAPI)
        assert registry.get("semapi_dsp_mx300") is SEMAPI


class TestResult:
    def test_every_importer_lands_on_the_same_shape(self):
        result = SEMAPI.parse(BytesIO(b""))
        assert result.source_instrument == "semapi_dsp_mx300"
        assert result.readings[0].point_label == "1H"
        assert not result.is_empty

    def test_an_empty_import_says_so_instead_of_looking_successful(self):
        assert ImportResult().is_empty
