"""Decode the upper-left Ding marker from an original WoW screenshot."""
from dataclasses import dataclass
from pathlib import Path
from statistics import median
import unicodedata

from PIL import Image


@dataclass(frozen=True)
class Event:
    key: str
    level: int
    test: bool
    name: str | None = None
    ping: bool = False


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
        corner = image.crop((0, 0, min(image.width, round(49 * cell)), round(12 * cell))).convert("L")

    rows = bytearray()
    length = 11
    for index in range(60):
        block, row = divmod(index, 11)
        if (9 + block * 8) * cell > corner.width + 0.5:
            return None
        value = 0
        for col in range(8 * block, 8 * block + 8):
            # Sample inside each tile, away from rasterization and JPEG edges.
            samples = [corner.getpixel((int((1 + col + x) * cell), int((1 + row + y) * cell)))
                       for x in (0.35, 0.5, 0.65) for y in (0.35, 0.5, 0.65)]
            light = median(samples)
            if 65 < light < 190:
                return None
            value = (value << 1) | (light >= 190)
        rows.append(value)
        if index < 2 and value != (0xD6, 0x39)[index]:
            return None
        if index == 2 and value not in (0x10, 0x11, 0x20, 0x22):
            return None
        if index == 10 and rows[2] in (0x20, 0x22):
            if not 1 <= value <= 48:
                return None
            length = 12 + value
        if len(rows) == length:
            break
    if rows[3] == 0 or checksum(rows[:-1]) != rows[-1]:
        return None
    name = None
    if rows[2] in (0x20, 0x22):
        try:
            name = rows[11:-1].decode("utf-8")
        except UnicodeDecodeError:
            return None
        if not name[0].isalpha() or not all(c.isalpha() or unicodedata.category(c) in {"Mn", "Mc"} for c in name):
            return None
    return Event(rows[2:10].hex(), rows[3], rows[2] == 0x11, name, rows[2] == 0x22)
