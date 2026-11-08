from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


@unittest.skipUnless(sys.platform.startswith("linux"), "requires Linux")
class LinuxSetup(unittest.TestCase):
    def setUp(self):
        import linux_app
        self.app = linux_app
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.game = self.root / "Wine prefix/drive_c/World of Warcraft/_forever_"
        self.game.mkdir(parents=True)
        (self.game / "WoW.exe").touch()
        for attr, value in {"CONFIG": self.root / "config/settings.json", "STATE": self.root / "state",
                            "AUTOSTART": self.root / "autostart/wow-ding.desktop"}.items():
            self.enter_patch(patch.object(self.app, attr, value))
        self.secret = "https://discord.com/api/webhooks/1/fixture-only"
        self.verify = self.enter_patch(patch.object(self.app, "verify_secret", return_value="10"))
        self.vault = self.enter_patch(patch.object(self.app, "credential", return_value=self.secret))

    def enter_patch(self, mock):
        self.addCleanup(mock.stop)
        return mock.start()

    def test_connect_rotate_change_channel_and_remove(self):
        first = self.app.connect(self.game.parent, self.secret, True)
        payload = self.game / "Interface/AddOns/Ding/Ding.lua"
        self.assertEqual(payload.read_bytes(), (self.app.addon.SOURCE / "Ding.lua").read_bytes())
        self.assertTrue((self.app.STATE / first["state"]).is_file())
        self.assertTrue(self.app.AUTOSTART.is_file())
        self.assertNotIn("fixture-only", self.app.CONFIG.read_text() + self.app.AUTOSTART.read_text())
        again = self.app.connect(self.game, "", False)
        self.assertEqual(first["state"], again["state"])
        self.assertFalse(self.app.AUTOSTART.exists())
        self.vault.assert_any_call("lookup", "10")
        self.verify.return_value = "20"
        new = self.app.connect(self.game, self.secret, True)
        self.assertNotEqual(first["state"], new["state"])
        self.vault.assert_any_call("clear", "10")
        payload.write_text("player edit")
        self.app.disconnect()
        self.assertEqual(payload.read_text(), "player edit")
        self.assertFalse(payload.with_suffix(".toc").exists())
        self.assertFalse(self.app.CONFIG.exists())
        self.assertFalse(self.app.AUTOSTART.exists())
        self.vault.assert_any_call("clear", "20")
        self.assertTrue((self.app.STATE / new["state"]).is_file())

    def test_invalid_game_webhook_and_symlink(self):
        with self.assertRaises(ValueError):
            self.app.connect(self.root, self.secret, False)
        self.verify.assert_not_called()
        self.verify.side_effect = ValueError("invalid webhook")
        with self.assertRaises(ValueError):
            self.app.connect(self.game, self.secret, False)
        self.assertFalse((self.game / "Interface").exists())
        self.verify.side_effect = None
        (self.game / "Screenshots").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.app.connect(self.game, self.secret, False)
        self.assertFalse(self.app.CONFIG.exists())

    def test_failed_keyring_and_single_watcher(self):
        self.vault.side_effect = ValueError("keyring locked")
        with self.assertRaises(ValueError):
            self.app.connect(self.game, self.secret, True)
        self.assertFalse(self.app.CONFIG.exists())
        self.assertFalse(self.app.AUTOSTART.exists())
        self.assertFalse((self.game / "Interface").exists())
        with self.app.lock("watch.lock"):
            with patch.object(self.app, "settings", side_effect=AssertionError("duplicate watcher ran")):
                self.app.background()
