"""Windowless Windows startup entry point and one-time credential setup."""
import argparse
import contextlib
import http.client
import json
import msvcrt
import os
from pathlib import Path
import sqlite3
import sys
import time
import uuid

import pywintypes
import win32cred
import win32timezone  # CredRead loads this dynamically to convert LastWritten. Bundle it in the Windows app.

from hook import Rejected, webhook_path
from watch import watch_folder
import addon


TARGET = "WoW Ding/Discord webhook"
ROOT = Path(os.environ["LOCALAPPDATA"]) / "WoWDing"


def load_secret():
    credential = win32cred.CredRead(TARGET, win32cred.CRED_TYPE_GENERIC)
    return credential["CredentialBlob"].decode("utf-16-le")


def verify_secret(secret, channel=None):
    path = webhook_path(secret).split("?")[0]
    conn = http.client.HTTPSConnection("discord.com", timeout=10)
    try:
        conn.request("GET", path, headers={"User-Agent": "WoW-Ding/1.1"})
        response = conn.getresponse()
        if response.status != 200:
            raise ValueError(f"Discord returned HTTP {response.status}. Check the webhook and try again.")
        metadata = json.loads(response.read(64_000))
        if channel and metadata.get("channel_id") != channel:
            raise ValueError("Please use the webhook for your existing WoW Ding channel.")
        if not isinstance(metadata.get("channel_id"), str) or not metadata["channel_id"].isascii() or not metadata["channel_id"].isdigit():
            raise ValueError("Choose a webhook for a Discord text channel.")
        return metadata["channel_id"]
    finally:
        conn.close()


def store_secret(secret):
    win32cred.CredWrite({
        "Type": win32cred.CRED_TYPE_GENERIC,
        "TargetName": TARGET,
        "UserName": "WoW Ding",
        "CredentialBlob": secret,
        "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
    }, 0)


def save_secret(secret, channel=None):
    verify_secret(secret, channel)
    store_secret(secret)


def settings():
    try:
        return json.loads((ROOT / "settings.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def connect(game_path, secret, channel=None):
    game = addon.forever(game_path)
    if not secret:
        try:
            secret = load_secret()
        except pywintypes.error as exc:
            if exc.winerror == 1168:
                raise ValueError("Paste a Discord webhook to connect your channel.") from None
            raise
    destination = verify_secret(secret, channel)
    old = settings()
    same_game = old and Path(old["game"]) == game
    ROOT.mkdir(parents=True, exist_ok=True)
    (game / "Screenshots").mkdir(exist_ok=True)
    files = addon.install_addon(game, old["files"] if same_game else {})
    # A different folder/channel starts a new delivery history.
    state = old["state"] if same_game and old["channel"] == destination else f"{uuid.uuid4().hex}.db"
    config = {"game": str(game), "state": state, "channel": destination, "files": files,
              "revision": uuid.uuid4().hex, "owner": str(Path(sys.executable).resolve())}
    store_secret(secret)
    addon.write_file(ROOT / "settings.json", json.dumps(config).encode("utf-8"))
    if old and not same_game:
        addon.remove_addon(old)
    return config


def cleanup():
    config = settings()
    if not config or Path(config["owner"]) != Path(sys.executable).resolve():
        return
    addon.remove_addon(config)
    (ROOT / "settings.json").unlink()
    try:
        win32cred.CredDelete(TARGET, win32cred.CRED_TYPE_GENERIC)
    except pywintypes.error as exc:
        if exc.winerror != 1168:
            raise


def status(message):
    temp = ROOT / "status.tmp"
    temp.write_text(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  PID {os.getpid()}  {message}\n", encoding="utf-8")
    temp.replace(ROOT / "status.txt")


def background(folder=None):
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / "watch.lock").open("a+b") as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return  # Another background watcher owns the lock for this account.
        with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink):
            while True:
                try:
                    config = settings()
                    if folder is None and not config:
                        return
                    shots = Path(config["game"]) / "Screenshots" if config else folder
                    state = ROOT / (config["state"] if config else "events.db")
                    endpoint = webhook_path(load_secret())
                    if shots.is_dir():
                        watch_folder(shots, endpoint, state, ready=lambda: status("Watching screenshots"),
                                     running=lambda: settings().get("revision") == config.get("revision"))
                        continue
                    else:
                        status("Waiting for screenshot folder")
                except (pywintypes.error, UnicodeError, ValueError, Rejected):
                    status("Check the saved webhook in WoW Ding setup")
                except (OSError, sqlite3.Error):
                    status("Waiting for access to the screenshot folder or local database")
                time.sleep(5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", nargs="?", type=Path)
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--remove", action="store_true")
    parser.add_argument("--channel", help="verify the intended Discord channel during setup")
    args = parser.parse_args()
    if args.remove:
        cleanup()
    elif args.watch:
        background()
    elif args.folder:
        background(args.folder)
    else:
        from welcome import show
        show(sys.modules[__name__], args.channel)
