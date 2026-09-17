from __future__ import annotations

from modules.core.domain.errors import DomainError


class OverlappingBands(DomainError):
    code = "overlapping_bands"

    def __init__(self, first: str, second: str) -> None:
        super().__init__(f"Bands '{first}' and '{second}' overlap")


class UnknownMagnitude(DomainError):
    code = "unknown_magnitude"


class StatusNotInProfile(DomainError):
    code = "status_not_in_profile"

    def __init__(self, status_code: str, technique_code: str) -> None:
        super().__init__(f"'{status_code}' is not a status of technique '{technique_code}'")
        self.status_code = status_code
        self.technique_code = technique_code


class UnknownStandard(DomainError):
    code = "unknown_standard"


class StandardTechniqueMismatch(DomainError):
    code = "standard_technique_mismatch"

    def __init__(self, standard_code: str, magnitude_code: str, technique_code: str | None) -> None:
        super().__init__(
            f"'{standard_code}' does not cover technique "
            f"'{technique_code or 'unknown'}' required by magnitude '{magnitude_code}'"
        )
        self.standard_code = standard_code
        self.magnitude_code = magnitude_code
        self.technique_code = technique_code
