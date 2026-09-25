"""V3-07: the latest intervention wins, whatever produced it."""

from datetime import UTC, datetime

from modules.services.domain.intervention import Intervention, latest


def test_the_most_recent_one_wins():
    vibration = Intervention(datetime(2026, 9, 12, tzinfo=UTC), "Vibraciones")
    thermography = Intervention(datetime(2026, 9, 18, tzinfo=UTC), "Termografía")
    assert latest([vibration, thermography, None]) is thermography


def test_a_train_never_touched_has_none():
    assert latest([None, None]) is None
    assert latest([]) is None
