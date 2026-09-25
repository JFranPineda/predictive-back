"""V3-10: the record prints velocity, acceleration, envelope, temperature."""

from modules.measurements.domain.magnitude_order import block_sort_key, display_order_for

BLOCKS = ["env_accel:peak", "temp:max", "vel_rms:rms", "accel_rms:rms"]


def test_the_sheet_order_not_the_alphabet():
    ordered = sorted(BLOCKS, key=lambda key: block_sort_key(display_order_for(key.split(":")[0]), key))
    assert ordered == ["vel_rms:rms", "accel_rms:rms", "env_accel:peak", "temp:max"]


def test_an_unlisted_magnitude_goes_last():
    assert display_order_for("brand_new") > display_order_for("dielectric_kv")


def test_ties_break_on_the_block_key():
    assert block_sort_key(30, "env_accel:peak") < block_sort_key(30, "env_accel:peak_to_peak")
