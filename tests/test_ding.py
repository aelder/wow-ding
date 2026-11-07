import contextlib
import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from lupa.luajit21 import LuaRuntime
from PIL import Image, ImageDraw

import hook
import marker
import watch


ROOT = Path(__file__).resolve().parents[1]


class Addon:
    def __init__(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute((ROOT / "tests/wow.lua").read_text())
        self.lua.execute((ROOT / "Ding/Ding.lua").read_text())
        self.g = self.lua.globals()

    def capture(self, level=42, test=False, height=1080):
        if test:
            self.g.SlashCmdList.WOWDING("test")
        else:
            self.g.fire("PLAYER_LEVEL_UP", level)
        for _ in range(3):
            self.g.tick()
        frame = self.g.frames[1]
        assert frame.shown and self.g.shots == 1
        image = Image.new("RGB", (height * 16 // 9, height), (49, 73, 108))
        draw = ImageDraw.Draw(image)
        scale = height / self.g.UIParent.GetHeight()
        for tile in frame.tiles.values():
            x, y = frame.x + tile.x, frame.y + tile.y
            draw.rectangle((round(x * scale), round(y * scale),
                            round((x + tile.w) * scale) - 1, round((y + tile.h) * scale) - 1),
                           fill=(255 * tile.color,) * 3)
        return image


class Files(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.file = self.folder / "wow.jpg"

    def test_addon_to_decoder(self):
        for level, height, fmt in [(1, 600, "JPEG"), (42, 1080, "JPEG"), (60, 1440, "TGA"),
                                   (127, 768, "PNG"), (255, 2160, "JPEG"), (128, 937, "JPEG")]:
            with self.subTest(level=level):
                Addon().capture(level, height=height).save(self.file, format=fmt, quality=35)
                event = marker.decode(self.file)
                self.assertEqual((event.level, event.test), (level, False))

    def test_diagnostic_marker(self):
        Addon().capture(test=True).save(self.file)
        self.assertTrue(marker.decode(self.file).test)
        self.assertEqual(marker.decode(self.file).level, 42)

    def test_corrupt_ordinary_and_unknown(self):
        image = Addon().capture(height=960)
        for row in [0, 2, 3, 9, 10]:
            with self.subTest(row=row):
                bad = image.copy()
                tile = (10, (1 + row) * 10, 19, (2 + row) * 10 - 1)
                color = 255 - image.getpixel((15, (1 + row) * 10 + 5))[0]
                ImageDraw.Draw(bad).rectangle(tile, fill=(color,) * 3)
                bad.save(self.file)
                self.assertIsNone(marker.decode(self.file))
        for color in ["black", "white", "gray"]:
            Image.new("RGB", (1280, 720), color).save(self.file)
            self.assertIsNone(marker.decode(self.file))

    def test_capture_queue_render_wait_failure_timeout(self):
        game = Addon().g
        game.fire("PLAYER_LEVEL_UP", 0)
        game.fire("PLAYER_LEVEL_UP", 256)
        game.fire("PLAYER_LEVEL_UP", 1.5)
        self.assertFalse(game.frames[1].shown)
        game.fire("PLAYER_LEVEL_UP", 20)
        game.fire("PLAYER_LEVEL_UP", 21)
        game.fire("SCREENSHOT_SUCCEEDED")
        game.tick()
        game.tick()
        self.assertEqual(game.shots, 0)
        game.tick()
        self.assertEqual(game.shots, 1)
        game.fire("SCREENSHOT_FAILED")
        self.assertFalse(game.frames[1].shown)
        game.timer(1.2)
        for _ in range(3):
            game.tick()
        self.assertEqual(game.shots, 2)
        game.timer(10)  # Old timeout must not hide the new marker.
        self.assertTrue(game.frames[1].shown)
        game.timer(10)
        self.assertFalse(game.frames[1].shown)

    def test_hidden_ui(self):
        game = Addon().g
        game.uiVisible = False
        game.fire("PLAYER_LEVEL_UP", 42)
        game.tick()
        self.assertFalse(game.frames[1].shown)
        self.assertEqual(game.shots, 0)

    def test_partial_rewrite_baseline_and_restart(self):
        state = self.folder / "state.db"
        db = watch.open_store(state)
        since = db.execute("SELECT since_ns FROM meta").fetchone()[0]
        scan = watch.Scanner(self.folder, since)
        old = self.folder / "old.png"
        Addon().capture(3).save(old)
        os.utime(old, ns=(since - 1_000_000, since - 1_000_000))
        self.file.write_bytes(b"\xff\xd8")
        scan.scan(lambda _: self.fail())
        scan.scan(lambda _: self.fail())
        Addon().capture(24).save(self.file)
        scan.scan(lambda _: self.fail())
        scan.scan(lambda event: watch.enqueue(db, event))
        scan.scan(lambda _: self.fail())
        db.close()
        with contextlib.closing(watch.open_store(state)) as db:
            scan = watch.Scanner(self.folder, since)
            for _ in range(2):
                scan.scan(lambda event: watch.enqueue(db, event))
            sent = []
            watch.deliver(db, sent.append)
            watch.deliver(db, sent.append)
            self.assertEqual(sent, [24])

    def test_rate_limit_queue_survives_restart(self):
        state = self.folder / "state.db"
        with contextlib.closing(watch.open_store(state)) as db:
            for i in range(2):
                watch.enqueue(db, marker.Event(str(i), 40 + i, False))
            with patch("watch.time.time", return_value=100):
                watch.deliver(db, lambda _: self.rate_limit())
        with contextlib.closing(watch.open_store(state)) as db:
            sent = []
            with patch("watch.time.time", return_value=119):
                watch.deliver(db, sent.append)
            self.assertFalse(sent)
            with patch("watch.time.time", return_value=120):
                watch.deliver(db, sent.append)
                watch.deliver(db, sent.append)
            self.assertEqual(sent, [40, 41])

    def test_watch_modes(self):
        for live in (False, True):
            with self.subTest(live=live):
                folder = self.folder / str(live)
                folder.mkdir()
                state = folder / "events.db"
                args = ["watch.py", str(folder), "--state", str(state)]
                if live:
                    args.append("--send")
                ticks = 0

                def clock_tick(_):
                    nonlocal ticks
                    if ticks == 0:
                        Addon().capture(19).save(folder / "real.jpg")
                        Addon().capture(test=True).save(folder / "test.jpg")
                    ticks += 1
                    if ticks == 4:
                        raise KeyboardInterrupt

                output = StringIO()
                with (patch("sys.argv", args), patch("watch.time.sleep", side_effect=clock_tick),
                      patch.dict(os.environ, {"DISCORD_WEBHOOK": "https://discord.com/api/webhooks/1/test_only"}),
                      patch("watch.post") as send, contextlib.redirect_stdout(output),
                      self.assertRaises(KeyboardInterrupt)):
                    watch.run()
                self.assertIn("Test marker decoded: level 42", output.getvalue())
                self.assertNotIn("test_only", output.getvalue())
                self.assertEqual(state.exists(), live)
                if live:
                    send.assert_called_once_with("/api/webhooks/1/test_only?wait=true", 19)
                else:
                    send.assert_not_called()
                    self.assertIn("Dry run: level 19", output.getvalue())

    @staticmethod
    def rate_limit():
        raise hook.Retry(20)


class Webhook(unittest.TestCase):
    def test_destination_validation(self):
        valid = "https://discord.com/api/webhooks/123/test_token"
        self.assertTrue(hook.webhook_path(valid).endswith("?wait=true"))
        for bad in [valid.replace("https:", "http:"), valid.replace("discord.com", "discord.com.evil"),
                    valid + "?x=y", valid + "/x", valid.replace("discord.com", "name@discord.com")]:
            with self.assertRaises(ValueError):
                hook.webhook_path(bad)

    def test_http_contract_and_errors(self):
        received = []
        status = 200

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                content = self.rfile.read(int(self.headers["Content-Length"]))
                received.append((self.path, self.headers["Content-Type"], json.loads(content)))
                self.send_response(status)
                self.send_header("Retry-After", "5")
                self.end_headers()
                self.wfile.write(b'{"retry_after":6.5}')

            def log_message(self, *args):
                pass

        with HTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                def local_connection(host, timeout):
                    self.assertEqual(host, "discord.com")
                    return http.client.HTTPConnection(*server.server_address, timeout=timeout)

                path = hook.webhook_path("https://discord.com/api/webhooks/1/test_only")
                with patch("hook.http.client.HTTPSConnection", side_effect=local_connection):
                    hook.post(path, 42)
                    self.assertEqual(received[0], (path, "application/json",
                                     {"content": "Ding! Reached level 42 in WoW.",
                                      "allowed_mentions": {"parse": []}}))
                    status = 429
                    with self.assertRaises(hook.Retry) as ctx:
                        hook.post(path, 42)
                    self.assertEqual(ctx.exception.delay, 6.5)
                    status = 503
                    with self.assertRaises(hook.Retry):
                        hook.post(path, 42)
                    for status in (302, 401, 404):
                        with self.assertRaises(hook.Rejected) as ctx:
                            hook.post(path, 42)
                        self.assertNotIn("test_only", str(ctx.exception))
            finally:
                server.shutdown()
                thread.join()


if __name__ == "__main__":
    unittest.main()
