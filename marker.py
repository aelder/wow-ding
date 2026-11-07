"""Decode the upper-left Ding marker from an original WoW screenshot."""
from dataclasses import dataclass
from pathlib import Path
from statistics import median

from PIL import Image


@dataclass(frozen=True)
class Event:
    key: str
    level: int
    test: bool


def checksum(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ (7 if crc & 128 else 0)) & 255
    return crc


def decode(path: Path) -> Event | None:
    with Image.open(path, formats=("JPEG", "PNG", "TGA")) as image:
        cell = image.height / 96
        if cell < 4 or image.width < 9 * cell or image.width * image.height > 40_000_000:
            return None
        corner = image.crop((0, 0, round(9 * cell), round(12 * cell))).convert("L")

    rows = bytearray()
    for row in range(11):
        value = 0
        for col in range(8):
            # Sample inside each tile, away from rasterization and JPEG edges.
            samples = [corner.getpixel((int((1 + col + x) * cell), int((1 + row + y) * cell)))
                       for x in (0.35, 0.5, 0.65) for y in (0.35, 0.5, 0.65)]
            light = median(samples)
            if 65 < light < 190:
                return None
            value = (value << 1) | (light >= 190)
        rows.append(value)
        if row < 2 and value != (0xD6, 0x39)[row]:
            return None
    if rows[2] not in (0x10, 0x11) or rows[3] == 0 or checksum(rows[:-1]) != rows[-1]:
        return None
    return Event(rows[2:-1].hex(), rows[3], rows[2] == 0x11)
