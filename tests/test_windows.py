import importlib.util
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
            proc = subprocess.Popen([os.environ["WOWDING_EXE"], str(screenshots)],
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
                if proc.poll() is None:
                    proc.terminate()
                proc.wait(timeout=10)

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
