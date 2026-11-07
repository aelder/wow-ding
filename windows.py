"""Windowless Windows startup entry point and one-time credential setup."""
import argparse
import contextlib
import http.client
import json
import msvcrt
import os
from pathlib import Path
import sqlite3
import time

import pywintypes
import win32cred
import win32timezone  # CredRead loads this dynamically to convert LastWritten. Bundle it in the Windows app.

from hook import Rejected, webhook_path
from watch import watch_folder


TARGET = "WoW Ding/Discord webhook"
ROOT = Path(os.environ["LOCALAPPDATA"]) / "WoWDing"


def load_secret():
    credential = win32cred.CredRead(TARGET, win32cred.CRED_TYPE_GENERIC)
    return credential["CredentialBlob"].decode("utf-16-le")


def save_secret(secret, channel=None):
    path = webhook_path(secret).split("?")[0]
    conn = http.client.HTTPSConnection("discord.com", timeout=10)
    try:
        conn.request("GET", path, headers={"User-Agent": "WoW-Ding/1.1"})
        response = conn.getresponse()
        if response.status != 200:
            raise ValueError("Discord could not verify the webhook. Check the URL and try again.")
        metadata = json.loads(response.read(64_000))
        if channel and metadata.get("channel_id") != channel:
            raise ValueError("Please use the webhook for your existing WoW Ding channel.")
    finally:
        conn.close()
    win32cred.CredWrite({
        "Type": win32cred.CRED_TYPE_GENERIC,
        "TargetName": TARGET,
        "UserName": "WoW Ding",
        "CredentialBlob": secret,
        "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
    }, 0)


def configure(channel):
    import tkinter as tk
    from tkinter import ttk

    window = tk.Tk()
    window.title("WoW Ding • Save Discord webhook")
    panel = ttk.Frame(window, padding=18)
    panel.pack(fill="both", expand=True)
    ttk.Label(panel, text="Paste your Discord webhook to save it for this Windows account.").pack(anchor="w")
    entry = ttk.Entry(panel, width=58, show="*")
    entry.pack(pady=10, fill="x")
    feedback = ttk.Label(panel, text="")
    feedback.pack(anchor="w")

    def save(*_):
        try:
            save_secret(entry.get().strip(), channel)
        except (OSError, ValueError, http.client.HTTPException, pywintypes.error):
            feedback.configure(text="Could not save. Check the channel webhook and your connection, then retry.")
            return
        entry.delete(0, "end")
        window.destroy()

    ttk.Button(panel, text="Save webhook", command=save).pack(anchor="e")
    window.bind("<Return>", save)
    entry.focus_force()
    window.mainloop()


def status(message):
    temp = ROOT / "status.tmp"
    temp.write_text(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  PID {os.getpid()}  {message}\n", encoding="utf-8")
    temp.replace(ROOT / "status.txt")


def background(folder):
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
                    endpoint = webhook_path(load_secret())
                    if folder.is_dir():
                        watch_folder(folder, endpoint, ROOT / "events.db", ready=lambda: status("Watching screenshots"))
                    else:
                        status("Waiting for screenshot folder")
                except (pywintypes.error, UnicodeError, ValueError, Rejected):
                    status("Check the saved webhook in WoW Ding setup")
                except (OSError, sqlite3.Error):
                    status("Waiting for access to the screenshot folder or local database")
                time.sleep(30)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", nargs="?", type=Path)
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--channel", help="verify the intended Discord channel during setup")
    args = parser.parse_args()
    if args.setup:
        configure(args.channel)
    elif args.folder:
        background(args.folder)
    else:
        parser.error("Supply the Screenshots folder, or use --setup to save a webhook.")
