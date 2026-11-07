import importlib.util
import sys
import unittest
import uuid
from unittest.mock import patch


@unittest.skipUnless(sys.platform == "win32" and importlib.util.find_spec("win32cred"),
                     "requires Windows and win.txt")
class WindowsStartup(unittest.TestCase):
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
