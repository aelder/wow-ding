"""Render the shipped addon using the project's existing WoW harness."""
import json
from pathlib import Path
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from test_ding import Addon
from marker import decode

folder = Path(sys.argv[1])
manifest = {}
for file, height, options in [
    ("real.jpg", 937, {"level": 25}),
    ("ping.png", 1080, {"ping": True}),
    ("local.tga", 1440, {"test": True}),
    ("legacy.jpg", 600, {"level": 9}),
    ("long.tga", 2160, {"level": 255}),
    ("unsafe.png", 768, {}),
]:
    addon = Addon()
    override = {"legacy.jpg": "", "long.tga": "𠀀" * 12, "unsafe.png": "@everyone"}
    if file in override:
        addon.g.UnitName = lambda _: override[file]
    addon.capture(height=height, **options).save(folder / file, quality=35)
    event = decode(folder / file)
    manifest[file] = (dict(id=event.key, level=event.level, name=event.name,
                           kind=int(event.key[:2], 16)) if event else None)
Image.new("RGB", (1280, 720), "gray").save(folder / "plain.jpg")
manifest["plain.jpg"] = None
(folder / "fixtures.json").write_text(json.dumps(manifest), encoding="utf-8")
