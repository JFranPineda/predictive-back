"""V3-31: "Otros" must say what was found."""

import pytest

from modules.diagnostics.domain.other_fault import (
    OtherFaultWithoutDescriptionError,
    other_fault_text,
)


def test_not_marked_keeps_nothing():
    assert other_fault_text(False, "tubería suelta") == ""


def test_marked_keeps_the_description():
    assert other_fault_text(True, "  vibración por tubería suelta ") == "vibración por tubería suelta"


def test_marked_without_a_description_is_refused():
    with pytest.raises(OtherFaultWithoutDescriptionError):
        other_fault_text(True, "   ")
