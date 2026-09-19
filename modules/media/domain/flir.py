"""Reading the radiometric payload a FLIR camera hides inside a JPEG.

A thermogram is a measurement, not a picture: the temperature of every pixel
is reconstructed from a raw sensor image plus the camera's calibration
constants, both carried in an APP1 segment tagged `FLIR`. Re-encoding the
JPEG throws that away and leaves something that only looks like a thermogram.

Parsing it here, in the domain and with the standard library only, is what
lets the nightly job store the matrix instead of raising — and what makes the
`temperature_at` arithmetic testable without a camera.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

FLIR_APP1 = b"\xff\xe1"
FLIR_MAGIC = b"FLIR\x00"
FFF_MAGIC = b"FFF\x00"

# Record types of the FFF tag table we care about.
RECORD_RAW_DATA = 1
RECORD_CAMERA_INFO = 32


@dataclass(frozen=True)
class CameraCalibration:
    """Planck constants and the scene terms the camera was set up with."""

    emissivity: float
    object_distance: float
    reflected_temperature: float
    atmospheric_temperature: float
    planck_r1: float
    planck_r2: float
    planck_b: float
    planck_f: float
    planck_o: float

    def as_dict(self) -> dict:
        return {
            "emissivity": self.emissivity,
            "object_distance_m": self.object_distance,
            "reflected_temperature_k": self.reflected_temperature,
            "atmospheric_temperature_k": self.atmospheric_temperature,
            "planck": {
                "r1": self.planck_r1, "r2": self.planck_r2, "b": self.planck_b,
                "f": self.planck_f, "o": self.planck_o,
            },
        }


@dataclass(frozen=True)
class Radiometric:
    calibration: CameraCalibration | None
    raw_thermal: bytes | None
    raw_format: str = ""
    width: int | None = None
    height: int | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def is_radiometric(self) -> bool:
        return self.raw_thermal is not None and self.calibration is not None


def extract(payload: bytes) -> Radiometric:
    """Pulls the FLIR record out of a JPEG. Never raises on a plain photo."""

    segment = _flir_segment(payload)
    if segment is None:
        return Radiometric(None, None, notes=["no FLIR APP1 segment"])
    if not segment.startswith(FFF_MAGIC):
        return Radiometric(None, None, notes=["FLIR segment is not an FFF container"])

    records = _records(segment)
    raw = records.get(RECORD_RAW_DATA)
    info = records.get(RECORD_CAMERA_INFO)
    notes = []
    if raw is None:
        notes.append("no raw thermal image in the FLIR record")
    if info is None:
        notes.append("no camera calibration in the FLIR record")

    thermal, fmt, width, height = _raw_image(raw) if raw else (None, "", None, None)
    return Radiometric(
        calibration=_calibration(info) if info else None,
        raw_thermal=thermal,
        raw_format=fmt,
        width=width,
        height=height,
        notes=notes,
    )


def temperature_at(raw_value: int, calibration: CameraCalibration) -> float:
    """Sensor count to °C, by the Planck curve the camera was calibrated on.

    Only the object signal is inverted here; the atmospheric and reflected
    terms are left to whoever needs the full radiometric correction. For the
    ΔT criteria the reports use, this is the number that matters.
    """
    import math

    denominator = raw_value - calibration.planck_o
    if denominator <= 0:
        return float("nan")
    ratio = calibration.planck_r1 / (calibration.planck_r2 * denominator) + calibration.planck_f
    if ratio <= 1:
        return float("nan")
    return calibration.planck_b / math.log(ratio) - 273.15


def _flir_segment(payload: bytes) -> bytes | None:
    """FLIR splits its record over as many APP1 chunks as it needs."""

    chunks: dict[int, bytes] = {}
    offset = 2
    total = len(payload)
    while offset + 4 <= total:
        if payload[offset : offset + 2] != FLIR_APP1:
            marker = payload[offset : offset + 2]
            if not marker.startswith(b"\xff") or marker == b"\xff\xda":
                break
            offset += 2 + struct.unpack(">H", payload[offset + 2 : offset + 4])[0]
            continue
        length = struct.unpack(">H", payload[offset + 2 : offset + 4])[0]
        body = payload[offset + 4 : offset + 2 + length]
        if body.startswith(FLIR_MAGIC) and len(body) > 8:
            index = body[6]
            chunks[index] = body[8:]
        offset += 2 + length
    if not chunks:
        return None
    return b"".join(chunks[key] for key in sorted(chunks))


def _records(segment: bytes) -> dict[int, bytes]:
    """The FFF tag table: type, offset and length of each record."""

    if len(segment) < 24:
        return {}
    index_offset, index_count = struct.unpack(">II", segment[16:24])
    records: dict[int, bytes] = {}
    for entry in range(index_count):
        base = index_offset + entry * 32
        if base + 32 > len(segment):
            break
        record_type, _, _, _, offset, length = struct.unpack(">HHIIII", segment[base : base + 20])
        if offset + length <= len(segment) and record_type not in records:
            records[record_type] = segment[offset : offset + length]
    return records


def _raw_image(record: bytes) -> tuple[bytes | None, str, int | None, int | None]:
    """The raw thermal image is either an embedded PNG or a plain 16-bit grid."""

    if record[:8] == b"\x89PNG\r\n\x1a\n":
        width, height = struct.unpack(">II", record[16:24])
        return record, "png", width, height
    if len(record) < 32:
        return None, "", None, None
    width, height = struct.unpack("<HH", record[2:6])
    body = record[32:]
    expected = width * height * 2
    if width and height and len(body) >= expected:
        return body[:expected], "raw16", width, height
    return None, "", None, None


def _calibration(record: bytes) -> CameraCalibration | None:
    # Offsets of the CameraInfo record, stable across the FFF revisions the
    # field cameras write.
    try:
        emissivity, distance, reflected = struct.unpack(">fff", record[32:44])
        atmospheric = struct.unpack(">f", record[48:52])[0]
        r1 = struct.unpack(">f", record[88:92])[0]
        b, f, o = struct.unpack(">ffi", record[92:104])
        r2 = struct.unpack(">f", record[112:116])[0]
    except struct.error:
        return None
    if not r1 or not r2:
        return None
    return CameraCalibration(
        emissivity=emissivity, object_distance=distance, reflected_temperature=reflected,
        atmospheric_temperature=atmospheric, planck_r1=r1, planck_r2=r2,
        planck_b=b, planck_f=f, planck_o=float(o),
    )
