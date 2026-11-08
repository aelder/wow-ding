"""Linux setup window."""
import contextlib
import queue
import sqlite3
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


def show(app):
    window = tk.Tk()
    window.title("WoW Ding")
    body = ttk.Frame(window, padding=20)
    body.grid(sticky="nsew")
    body.columnconfigure(0, weight=1)
    saved = app.settings()
    game = tk.StringVar(value=saved.get("game") or app.detect())
    secret = tk.StringVar()
    login = tk.BooleanVar(value=app.AUTOSTART.exists() if saved else True)
    message = tk.StringVar()
    results = queue.Queue()
    watching = saved
    baseline = 0
    busy = False

    ttk.Label(body, text="WoW Forever folder").grid(row=0, column=0, sticky="w")
    ttk.Entry(body, textvariable=game, width=55).grid(row=1, column=0, sticky="ew")

    def browse():
        selected = filedialog.askdirectory(parent=window, title="Choose World of Warcraft or _forever_")
        if selected:
            game.set(selected)

    ttk.Button(body, text="Browse…", command=browse).grid(row=1, column=1, padx=(6, 0))
    ttk.Label(body, text="Discord channel webhook").grid(row=2, column=0, sticky="w", pady=(14, 0))
    ttk.Entry(body, textvariable=secret, show="•").grid(row=3, column=0, columnspan=2, sticky="ew")
    hint = tk.StringVar()
    ttk.Label(body, textvariable=hint, wraplength=440).grid(row=4, column=0, columnspan=2, sticky="w")
    ttk.Checkbutton(body, text="Start the watcher at desktop login", variable=login).grid(
        row=5, column=0, columnspan=2, sticky="w", pady=10)
    ttk.Label(body, textvariable=message, wraplength=440).grid(row=6, column=0, columnspan=2, sticky="w")
    buttons = ttk.Frame(body)
    buttons.grid(row=7, column=0, columnspan=2, sticky="e", pady=(12, 0))

    def receipt(config, after):
        db_file = app.STATE / config["state"]
        with contextlib.closing(sqlite3.connect(db_file.as_uri() + "?mode=ro", uri=True, timeout=0.1)) as db:
            return db.execute("SELECT rowid, name, level FROM events WHERE ping=1 AND sent=1 AND rowid>? "
                              "ORDER BY rowid DESC LIMIT 1", (after,)).fetchone()

    def submit(removing=False):
        nonlocal busy, watching
        if busy:
            return
        if removing and not messagebox.askyesno("Disconnect WoW Ding?",
                "Remove the saved webhook, login entry and unmodified addon files?", parent=window):
            return
        busy = True
        watching = {}
        connect_button.state(["disabled"])
        remove_button.state(["disabled"])
        window.protocol("WM_DELETE_WINDOW", lambda: None)
        path, token, at_login = game.get(), secret.get().strip(), login.get()
        message.set("Disconnecting…" if removing else "Checking the webhook and installing the addon…")

        def work():
            try:
                if removing:
                    app.disconnect()
                    results.put(({}, 0, "Disconnected."))
                else:
                    config = app.connect(path, token, at_login)
                    last = receipt(config, 0)
                    app.launch_watcher()
                    results.put((config, last[0] if last else 0, "In game, enter /reload and then /ding ping."))
            except ValueError as error:
                results.put((None, 0, str(error)))
            except Exception:
                results.put((None, 0, "Setup could not finish. Check the network, folder access and desktop keyring."))

        threading.Thread(target=work, daemon=True).start()

    connect_button = ttk.Button(buttons, text="Install addon and connect", command=submit)
    remove_button = ttk.Button(buttons, text="Disconnect…", command=lambda: submit(True))
    remove_button.pack(side="left", padx=5)
    connect_button.pack(side="right")

    def refresh():
        nonlocal busy, watching, baseline, saved
        try:
            config, baseline, feedback = results.get_nowait()
        except queue.Empty:
            config = None
        else:
            busy = False
            window.protocol("WM_DELETE_WINDOW", window.destroy)
            connect_button.state(["!disabled"])
            message.set(feedback)
            saved = app.settings()
            if config is not None:
                secret.set("")
                watching = config
        if not busy:
            remove_button.state(["!disabled"] if saved else ["disabled"])
            hint.set("Leave blank to reuse your saved webhook." if saved else
                     "In Discord, open Edit Channel → Integrations → Webhooks and copy the channel webhook URL.")
        if watching and not busy:
            try:
                accepted = receipt(watching, baseline)
                status = (app.STATE / "status").read_text() if (app.STATE / "status").exists() else ""
                if accepted:
                    message.set(f"Discord accepted the test ding for {accepted[1]}, level {accepted[2]}.")
                elif status:
                    message.set(status + " In game, enter /reload and then /ding ping.")
            except (OSError, sqlite3.Error):
                pass
        window.after(1000, refresh)

    if saved:
        app.launch_watcher()
    refresh()
    window.mainloop()
