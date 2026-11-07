"""Windows first-run and settings window."""
import http.client
from pathlib import Path
import queue
import sqlite3
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, ttk

import pywintypes

import addon


def show(app, channel=None):
    window = tk.Tk()
    window.title("WoW Ding")
    window.resizable(False, False)
    body = ttk.Frame(window, padding=(24, 20))
    body.pack(fill="both", expand=True)
    existing = app.settings()
    detected = existing.get("game") or addon.detect()
    location = tk.StringVar(value=str(detected or ""))
    token = tk.StringVar()
    message = tk.StringVar()
    result = queue.Queue()
    width = 480

    def label(text, **options):
        return ttk.Label(body, text=text, wraplength=width, justify="left", **options)

    label("WoW Ding", font=("Segoe UI", 19, "bold")).pack(anchor="w")
    label("Send your character’s name and level to a Discord text channel. Screenshots stay on this PC.").pack(anchor="w", pady=(4, 15))
    label("World of Warcraft: Forever folder").pack(anchor="w")
    row = ttk.Frame(body)
    row.pack(fill="x", pady=(4, 14))
    ttk.Entry(row, textvariable=location, width=46).pack(side="left", fill="x", expand=True)

    def browse():
        selected = filedialog.askdirectory(parent=window, title="Select World of Warcraft or _forever_")
        if selected:
            location.set(selected)

    ttk.Button(row, text="Browse…", command=browse).pack(side="left", padx=(6, 0))
    label("Discord webhook").pack(anchor="w")
    try:
        app.load_secret()
        hint = "Your webhook is saved. Leave this blank to keep it, or paste a replacement."
    except (pywintypes.error, ValueError):
        hint = "In Discord: Edit Channel → Integrations → Webhooks → New Webhook → Copy Webhook URL. Paste it here."
    entry = ttk.Entry(body, textvariable=token, show="*", width=60)
    entry.pack(fill="x", pady=4)
    label(hint).pack(anchor="w")
    feedback = ttk.Label(body, textvariable=message, wraplength=width, justify="left")
    feedback.pack(anchor="w", pady=(12, 4))

    def check_test(state, baseline):
        try:
            uri = state.resolve().as_uri() + "?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=0.2) as db:
                event = db.execute("SELECT name, level FROM events WHERE ping=1 AND sent=1 AND rowid>? ORDER BY rowid DESC LIMIT 1", (baseline,)).fetchone()
        except sqlite3.Error:
            event = None
        if event:
            message.set(f"Discord accepted the test ding for {event[0]}, level {event[1]}.")
        else:
            window.after(1500, check_test, state, baseline)

    def finish():
        try:
            config, error = result.get_nowait()
        except queue.Empty:
            window.after(120, finish)
            return
        button.state(["!disabled"])
        window.protocol("WM_DELETE_WINDOW", window.destroy)
        if error:
            message.set(error)
            return
        token.set("")
        state = app.ROOT / config["state"]
        baseline = 0
        if state.exists():
            with sqlite3.connect(state) as db:
                baseline = db.execute("SELECT COALESCE(MAX(rowid),0) FROM events").fetchone()[0]
        cmd = [sys.executable]
        if not getattr(sys, "frozen", False):
            cmd.append(str(Path(__file__).with_name("windows.py")))
        subprocess.Popen(cmd + ["--watch"], creationflags=subprocess.CREATE_NO_WINDOW)
        for child in body.winfo_children():
            child.destroy()
        label("Test your first ding", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        label("In WoW Forever, enter /reload, then /ding ping. If the command is unknown, restart WoW and enable Ding in AddOns.").pack(anchor="w", pady=(8, 12))
        message.set("Waiting for a test ding…")
        ttk.Label(body, textvariable=message, wraplength=width).pack(anchor="w")
        label("You can close this window. The watcher runs in the background and starts at Windows sign-in.").pack(anchor="w", pady=(12, 8))
        ttk.Button(body, text="Done", command=window.destroy).pack(anchor="e")
        window.after(1000, check_test, state, baseline)

    def start():
        game, secret = location.get().strip(), token.get().strip()
        button.state(["disabled"])
        message.set("Checking Discord and installing the addon…")
        window.protocol("WM_DELETE_WINDOW", lambda: None)

        def work():
            try:
                config = app.connect(game, secret, channel)
                result.put((config, None))
            except ValueError as exc:
                result.put((None, str(exc)))
            except PermissionError:
                result.put((None, "Windows denied access. Check write access to the selected game folder and try again."))
            except (OSError, http.client.HTTPException, pywintypes.error):
                result.put((None, "Could not finish setup. Check your network, Windows Credential Manager and game folder, then retry."))
            except Exception:
                result.put((None, "Setup could not finish. Close this window and reopen WoW Ding to retry."))

        threading.Thread(target=work, daemon=True).start()
        window.after(120, finish)

    button = ttk.Button(body, text="Install addon and connect", command=start)
    button.pack(anchor="e")
    if detected:
        entry.focus_set()
    window.mainloop()
