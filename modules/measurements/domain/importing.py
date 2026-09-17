"""The seam for reading data out of an instrument.

Today the customer types the round in at the office — there is no signal in the
plant, so nothing is captured live. Tomorrow the same round arrives as the CSV
that a SEMAPI DSP Logger or an SKF Microlog exports.

Both paths land on the same `ImportResult`, so the use case that stores a round
never learns where the numbers came from. Parsers are registered, not hardcoded:
adding a third instrument is a new class and one `register()` call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import BinaryIO, Protocol, runtime_checkable

from modules.core.domain.errors import DomainError


class NoImporterForFile(DomainError):
    code = "no_importer_for_file"


class DuplicateImporter(DomainError):
    code = "duplicate_importer"


@dataclass(frozen=True, slots=True)
class ImportedReading:
    """A value as the instrument reports it, before it is matched to a point."""

    point_label: str
    magnitude_code: str
    value: Decimal | None
    unit_code: str
    aggregation: str
    taken_at: datetime
    equipment_tag: str | None = None
    route_name: str | None = None


@dataclass(frozen=True, slots=True)
class ImportedSpectrum:
    point_label: str
    spectrum_type: str
    taken_at: datetime
    fmin_hz: float
    fmax_hz: float
    amplitudes: tuple[float, ...]
    rpm_at_capture: float | None = None
    equipment_tag: str | None = None


@dataclass(slots=True)
class ImportResult:
    readings: tuple[ImportedReading, ...] = ()
    spectra: tuple[ImportedSpectrum, ...] = ()
    warnings: list[str] = field(default_factory=list)
    source_instrument: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.readings and not self.spectra


@runtime_checkable
class ReadingImporter(Protocol):
    """One instrument's export format."""

    code: str
    name: str
    extensions: tuple[str, ...]

    def supports(self, filename: str) -> bool: ...

    def parse(self, stream: BinaryIO) -> ImportResult: ...


class ImporterRegistry:
    def __init__(self) -> None:
        self._importers: dict[str, ReadingImporter] = {}

    def register(self, importer: ReadingImporter) -> None:
        if importer.code in self._importers:
            raise DuplicateImporter(importer.code)
        self._importers[importer.code] = importer

    def available(self) -> tuple[ReadingImporter, ...]:
        return tuple(sorted(self._importers.values(), key=lambda i: i.name))

    def get(self, code: str) -> ReadingImporter:
        try:
            return self._importers[code]
        except KeyError as exc:
            raise NoImporterForFile(code) from exc

    def for_file(self, filename: str) -> ReadingImporter:
        """Explicit choice beats sniffing, but a crew uploading 40 files should
        not have to pick 40 times."""
        for importer in self.available():
            if importer.supports(filename):
                return importer
        raise NoImporterForFile(filename)


registry = ImporterRegistry()
