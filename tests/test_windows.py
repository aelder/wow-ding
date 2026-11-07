import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch


@unittest.skipUnless(sys.platform == "win32" and importlib.util.find_spec("win32cred"),
                     "requires Windows and win.txt")
class WindowsStartup(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("WOWDING_EXE"), "set WOWDING_EXE to check the installed build with a saved webhook")
    def test_installed_app_reads_saved_credential(self):
        # The Windows vault remains user-scoped. Isolate the database and watch
        # an empty folder so this startup check cannot send a Discord message.
        with tempfile.TemporaryDirectory() as temp:
            screenshots = Path(temp) / "Screenshots"
            screenshots.mkdir()
            status = Path(temp) / "WoWDing" / "status.txt"
            status.parent.mkdir()
            config = status.with_name("settings.json")
            config.write_text(json.dumps({"game": temp, "state": "test.db", "revision": "test"}))
            proc = subprocess.Popen([os.environ["WOWDING_EXE"], "--watch"],
                                    env={**os.environ, "LOCALAPPDATA": temp})
            try:
                for _ in range(100):
                    if status.exists() and "Watching screenshots" in status.read_text(encoding="utf-8"):
                        break
                    self.assertIsNone(proc.poll(), "Packaged watcher exited during startup")
                    time.sleep(0.1)
                else:
                    self.fail("Packaged watcher did not start watching with the saved credential")
            finally:
                config.unlink(missing_ok=True)
                proc.wait(timeout=10)

    def test_setup_upgrade_and_removal(self):
        import windows
        import addon

        secret = "https://discord.com/api/webhooks/1/test_only"
        with tempfile.TemporaryDirectory() as work:
            game = Path(work) / "_forever_"
            game.mkdir()
            (game / "Wow.exe").touch()
            root = Path(work) / "user"
            with (patch.object(windows, "ROOT", root), patch.object(windows, "verify_secret", return_value="123") as verify,
                  patch.object(windows, "store_secret"), patch.object(windows, "load_secret", return_value=secret),
                  patch.object(windows.win32cred, "CredDelete") as forget):
                first = windows.connect(work, secret)
                addon_folder = game / "Interface" / "AddOns" / "Ding"
                self.assertEqual((addon_folder / "Ding.lua").read_bytes(), (addon.SOURCE / "Ding.lua").read_bytes())
                self.assertTrue((game / "Screenshots").is_dir())
                self.assertNotIn("test_only", (root / "settings.json").read_text())
                second = windows.connect(str(game), "")
                self.assertEqual(first["state"], second["state"])
                verify.return_value = "456"
                self.assertNotEqual(first["state"], windows.connect(work, secret)["state"])
                (addon_folder / "Ding.lua").write_text("-- user edit")
                with self.assertRaisesRegex(ValueError, "different addon"):
                    windows.connect(work, secret)
                windows.cleanup()
                self.assertEqual((addon_folder / "Ding.lua").read_text(), "-- user edit")
                self.assertFalse((addon_folder / "Ding.toc").exists())
                self.assertTrue((game / "Screenshots").is_dir())
                self.assertFalse((root / "settings.json").exists())
                forget.assert_called_once()

    def test_wrong_game_and_invalid_webhook(self):
        import windows

        with tempfile.TemporaryDirectory() as work:
            game = Path(work) / "_forever_"
            with self.assertRaisesRegex(ValueError, "_forever_"):
                windows.connect(work, "invalid")
            game.mkdir()
            (game / "Wow.exe").touch()
            with self.assertRaises(ValueError):
                windows.connect(work, "invalid")
            self.assertFalse((game / "Interface").exists())

    def test_verified_destination_and_credential_round_trip(self):
        import windows

        token = "https://discord.com/api/webhooks/1/test_only"
        target = "WoW Ding tests/" + uuid.uuid4().hex
        with patch.object(windows, "TARGET", target), patch("windows.http.client.HTTPSConnection") as connect:
            response = connect.return_value.getresponse.return_value
            response.status = 200
            response.read.return_value = b'{"channel_id":"123"}'
            with self.assertRaises(ValueError):
                windows.save_secret(token, channel="456")
            with self.assertRaises(windows.pywintypes.error):
                windows.load_secret()
            windows.save_secret(token, channel="123")
            try:
                self.assertEqual(windows.load_secret(), token)
                credential = windows.win32cred.CredRead(target, windows.win32cred.CRED_TYPE_GENERIC)
                self.assertEqual(credential["Persist"], windows.win32cred.CRED_PERSIST_LOCAL_MACHINE)
            finally:
                windows.win32cred.CredDelete(target, windows.win32cred.CRED_TYPE_GENERIC)
