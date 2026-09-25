"""V3-36: the ceiling of the plan."""

from modules.licensing.domain.usage import Usage, limit_message


def test_the_last_machine_of_the_plan_still_fits():
    assert Usage("equipment", 599, 600).fits()
    assert not Usage("equipment", 600, 600).fits()


def test_a_plan_without_a_ceiling_always_fits():
    assert Usage("equipment", 10_000, None).fits(adding=50)


def test_a_bulk_load_fits_all_or_nothing():
    assert not Usage("equipment", 580, 600).fits(adding=50)
    assert Usage("equipment", 550, 600).fits(adding=50)


def test_the_warning_starts_at_ninety_percent():
    assert not Usage("equipment", 539, 600).near_limit
    assert Usage("equipment", 540, 600).near_limit
    assert not Usage("equipment", 999, None).near_limit


def test_the_message_names_the_resource_in_spanish():
    assert limit_message(Usage("equipment", 600, 600)) == (
        "Tu plan permite 600 equipos y ya tienes 600. Contacta con 1A-MIG para ampliarlo."
    )
    assert "solo admite 20 más" in limit_message(Usage("equipment", 580, 600), adding=50)
