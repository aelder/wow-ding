"""WoW Ding desktop setup and watcher for a Linux Wine or Proton installation."""
import argparse
import contextlib
import fcntl
import http.client
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import uuid

import addon
from hook import Rejected, verify_secret, webhook_path
from watch import open_store, watch_folder


CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
CONFIG = CONFIG_HOME / "wow-ding" / "settings.json"
STATE = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "wow-ding"
AUTOSTART = CONFIG_HOME / "autostart" / "wow-ding.desktop"


def settings():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


@contextlib.contextmanager
def lock(name, nonblocking=False):
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (STATE / name).open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0))
        except BlockingIOError:
            yield False
            return
        yield True


def game_folder(path):
    if not path:
        raise ValueError("Choose the WoW Forever game folder.")
    parent = Path(path).expanduser()
    for candidate in (parent, parent / "_forever_"):
        if candidate.name == "_forever_" and candidate.is_dir() and any(
            item.name.casefold() == "wow.exe" and item.is_file() for item in candidate.iterdir()
        ):
            return candidate.resolve()
    raise ValueError("Choose the _forever_ folder containing Wow.exe, or its World of Warcraft parent.")


def detect():
    home = Path.home()
    prefixes = [Path(os.environ.get("WINEPREFIX") or home / ".wine"), home / "Games/battlenet"]
    for prefix in prefixes:
        candidate = prefix / "drive_c/Program Files (x86)/World of Warcraft"
        if candidate.is_dir():
            try:
                return str(game_folder(candidate))
            except (OSError, ValueError):
                pass
    return ""


def credential(action, channel, secret=None):
    command = ["secret-tool", action]
    if action == "store":
        command.append("--label=WoW Ding Discord webhook")
    command += ["application", "org.wow-ding.linux", "channel", channel]
    env = os.environ.copy()
    if getattr(sys, "frozen", False):
        # System libsecret must use the desktop's libraries, not the bundled ones.
        if "LD_LIBRARY_PATH_ORIG" in env:
            env["LD_LIBRARY_PATH"] = env["LD_LIBRARY_PATH_ORIG"]
        else:
            env.pop("LD_LIBRARY_PATH", None)
    try:
        result = subprocess.run(command, input=secret or "", text=True, capture_output=True, env=env, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("Install secret-tool and unlock your desktop Secret Service keyring.") from None
    if action == "clear" and result.returncode == 1 and not result.stderr.strip():
        return  # Already removed.
    if result.returncode:
        raise ValueError("Could not access the saved webhook. Unlock your desktop keyring and retry.")
    return result.stdout.strip()


def command():
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, str(Path(__file__).resolve())]


def set_autostart(enable):
    if not enable:
        AUTOSTART.unlink(missing_ok=True)
        return
    # Desktop Entry Exec quoting comes before the general string escaping.
    def quote(arg):
        if any(ord(ch) < 32 for ch in arg):
            raise ValueError("Move WoW Ding to a folder without control characters in its name.")
        escaped = "".join(("\\" + ch) if ch in ('"', "\\", "$", chr(96)) else ch for ch in arg)
        return '"' + escaped.replace("\\", "\\\\").replace("%", "%%") + '"'

    line = " ".join(quote(arg) for arg in command() + ["--watch"])
    AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
    addon.write_file(AUTOSTART, ("[Desktop Entry]\nType=Application\nName=WoW Ding\nExec=" + line + "\n").encode())


def connect(path, secret, autostart):
    with lock("settings.lock"):
        old = settings()
        game = game_folder(path)
        if not secret:
            if not old:
                raise ValueError("Paste the Discord channel webhook.")
            secret = credential("lookup", old["channel"])
        channel = verify_secret(secret)
        same_game = str(game) == old.get("game")
        shots = game / "Screenshots"
        if not shots.resolve().is_relative_to(game):
            raise ValueError("The Screenshots folder points outside this game installation.")
        credential("store", channel, secret)
        try:
            shots.mkdir(exist_ok=True)
            files = addon.install_addon(game, old["files"] if same_game else {})
            state = old["state"] if same_game and old["channel"] == channel else uuid.uuid4().hex + ".db"
            with contextlib.closing(open_store(STATE / state)):
                pass  # Establish the cutoff before the player can run /ding ping.
            config = dict(game=str(game), channel=channel, files=files, state=state, revision=uuid.uuid4().hex)
            CONFIG.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            set_autostart(autostart)
            addon.write_file(CONFIG, json.dumps(config).encode())
        except Exception:
            if old.get("channel") != channel:
                credential("clear", channel)
            raise
        if old and old["channel"] != channel:
            credential("clear", old["channel"])
        if old and not same_game:
            addon.remove_addon(old)
        return config


def disconnect():
    with lock("settings.lock"):
        old = settings()
        if old:
            credential("clear", old["channel"])
            addon.remove_addon(old)
            CONFIG.unlink()
        set_autostart(False)


def status(text):
    addon.write_file(STATE / "status", text.encode())


def background():
    with lock("watch.lock", nonblocking=True) as owner:
        if not owner:
            return
        while config := settings():
            try:
                game = Path(config["game"])
                shots = game / "Screenshots"
                if not shots.resolve().is_relative_to(game) or not shots.is_dir():
                    raise OSError("Game folder unavailable")
                endpoint = webhook_path(credential("lookup", config["channel"]))
                watch_folder(shots, endpoint, STATE / config["state"],
                             ready=lambda: status("Watching screenshots."),
                             running=lambda: settings().get("revision") == config["revision"])
                continue
            except Rejected:
                status("Discord rejected the webhook. Open WoW Ding and reconnect.")
            except ValueError:
                status("Unlock the desktop keyring or reconnect the webhook in WoW Ding.")
            except (OSError, sqlite3.Error):
                status("Waiting for the Screenshots folder or local delivery history.")
            for _ in range(15):
                if settings().get("revision") != config["revision"]:
                    break
                time.sleep(1)


def launch_watcher():
    subprocess.Popen(command() + ["--watch"], start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     env={**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"})


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--watch", action="store_true", help="watch the configured game in the background")
    mode.add_argument("--disconnect", action="store_true", help="remove the saved connection, addon and login entry")
    mode.add_argument("--dry-run", type=Path, metavar="SCREENSHOTS", help="decode new captures locally")
    args = parser.parse_args()
    if args.watch:
        background()
    elif args.disconnect:
        disconnect()
    elif args.dry_run is not None:
        if not args.dry_run.is_dir():
            parser.error("Select an existing Screenshots directory.")
        watch_folder(args.dry_run)
    else:
        from linux_ui import show
        show(sys.modules[__name__])


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        pass
    except ValueError as exc:
        sys.exit(str(exc))
    except (OSError, sqlite3.Error, http.client.HTTPException):
        sys.exit("Could not access the desktop keyring, game folder, or local settings.")
