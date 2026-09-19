"""The radiometric payload of a thermogram.

Without this the nightly job raised `NotImplementedError` on every thermogram
and the whole conversion of that asset was lost — derivatives included.
"""

import struct

from modules.media.domain.flir import CameraCalibration, extract, temperature_at


def build_jpeg_with_flir(records: dict[int, bytes]) -> bytes:
    """A JPEG carrying a FLIR APP1 segment, as the camera writes it."""
    header = bytearray(b"FFF\x00" + b"\x00" * 20)
    table_offset = 32
    struct.pack_into(">II", header, 16, table_offset, len(records))
    header += b"\x00" * (table_offset - len(header))

    entries = bytearray()
    body = bytearray()
    payload_start = table_offset + len(records) * 32
    for record_type, payload in records.items():
        entry = bytearray(32)
        struct.pack_into(">HHIIII", entry, 0, record_type, 0, 0, 0,
                         payload_start + len(body), len(payload))
        entries += entry
        body += payload
    segment = bytes(header) + bytes(entries) + bytes(body)

    app1 = b"FLIR\x00" + b"\x01\x00\x00" + segment
    return (
        b"\xff\xd8"
        + b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1
        + b"\xff\xda" + b"\x00\x02"
    )


def camera_info() -> bytes:
    record = bytearray(128)
    struct.pack_into(">fff", record, 32, 0.95, 1.5, 293.15)
    struct.pack_into(">f", record, 48, 293.15)
    struct.pack_into(">f", record, 88, 17096.453)
    struct.pack_into(">ffi", record, 92, 1428.0, 1.0, -342)
    struct.pack_into(">f", record, 112, 0.046642)
    return bytes(record)


def raw_thermal(width: int = 4, height: int = 2) -> bytes:
    record = bytearray(32)
    struct.pack_into("<HH", record, 2, width, height)
    return bytes(record) + b"\x00\x40" * (width * height)


def test_a_plain_photograph_has_no_radiometric_payload():
    result = extract(b"\xff\xd8\xff\xdb\x00\x02\xff\xda\x00\x02")

    assert result.is_radiometric is False
    assert result.notes == ["no FLIR APP1 segment"]


def test_a_thermogram_yields_its_calibration_and_its_raw_grid():
    payload = build_jpeg_with_flir({1: raw_thermal(), 32: camera_info()})

    result = extract(payload)

    assert result.is_radiometric is True
    assert result.raw_format == "raw16"
    assert (result.width, result.height) == (4, 2)
    # float32 round-trip: the camera stores single precision.
    assert abs(result.calibration.emissivity - 0.95) < 1e-6
    assert len(result.raw_thermal) == 4 * 2 * 2


def test_a_segment_without_calibration_is_reported_not_raised():
    payload = build_jpeg_with_flir({1: raw_thermal()})

    result = extract(payload)

    assert result.is_radiometric is False
    assert "no camera calibration in the FLIR record" in result.notes


def test_sensor_counts_become_degrees():
    calibration = CameraCalibration(
        emissivity=0.95, object_distance=1.5, reflected_temperature=293.15,
        atmospheric_temperature=293.15, planck_r1=17096.453, planck_r2=0.046642,
        planck_b=1428.0, planck_f=1.0, planck_o=-342.0,
    )

    # A room-temperature count and a hot one, on a real camera's constants.
    assert abs(temperature_at(3000, calibration) - 30.2) < 0.5
    assert temperature_at(16384, calibration) > 150


def test_a_count_below_the_offset_is_not_a_temperature():
    """Reading a number out of a pixel the sensor never lit is worse than
    reading nothing: it would be graded against a standard."""
    calibration = CameraCalibration(
        emissivity=0.95, object_distance=1.5, reflected_temperature=293.15,
        atmospheric_temperature=293.15, planck_r1=17096.453, planck_r2=0.046642,
        planck_b=1428.0, planck_f=1.0, planck_o=-342.0,
    )

    assert temperature_at(-1000, calibration) != temperature_at(-1000, calibration)
