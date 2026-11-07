"""Watch one local WoW Screenshots directory. Default mode has no network access."""
import argparse
import getpass
import os
from pathlib import Path
import sqlite3
import sys
import time

from PIL import Image

from hook import Rejected, Retry, post, webhook_path
from marker import decode


class Scanner:
    def __init__(self, folder, since_ns):
        self.folder = folder
        self.since_ns = since_ns
        self.observed = {}
        self.done = set()
        self.retry_at = {}

    def scan(self, accept):
        # Recheck size AND mtime on consecutive polls. Keep a changed or
        # temporarily unreadable file eligible until it can be decoded.
        current = {}
        with os.scandir(self.folder) as entries:
            for entry in entries:
                if Path(entry.name).suffix.lower() not in {".jpg", ".jpeg", ".png", ".tga"}:
                    continue
                try:
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if info.st_mtime_ns < self.since_ns:
                    continue
                signature = (info.st_size, info.st_mtime_ns)
                current[entry.name] = signature

        self.done.intersection_update(current)
        self.retry_at = {name: due for name, due in self.retry_at.items() if name in current}
        for name, signature in current.items():
            if self.observed.get(name) != signature:
                self.done.discard(name)
                self.retry_at.pop(name, None)
                continue
            if name in self.done or not signature[0] or self.retry_at.get(name, 0) > time.monotonic():
                continue
            if signature[0] > 256_000_000:
                self.done.add(name)
                continue
            try:
                path = self.folder / name
                event = decode(path)
                after = path.stat()
                if signature != (after.st_size, after.st_mtime_ns):
                    continue
            except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
                # A changed file is retried immediately after it settles. A
                # released OS lock might not change mtime, so also retry later.
                self.retry_at[name] = time.monotonic() + 60
                continue
            if event:
                accept(event)
            self.done.add(name)
        self.observed = current


def open_store(path):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    with db:
        db.execute("CREATE TABLE IF NOT EXISTS meta (id INTEGER PRIMARY KEY, since_ns INTEGER NOT NULL)")
        db.execute("INSERT OR IGNORE INTO meta VALUES (1, ?)", (time.time_ns(),))
        db.execute("""CREATE TABLE IF NOT EXISTS events (
                   id TEXT PRIMARY KEY, level INTEGER NOT NULL, sent INTEGER DEFAULT 0)""")
        db.execute("""CREATE TABLE IF NOT EXISTS delivery (
                   id INTEGER PRIMARY KEY, due REAL DEFAULT 0, attempts INTEGER DEFAULT 0)""")
        db.execute("INSERT OR IGNORE INTO delivery (id) VALUES (1)")
    return db


def enqueue(db, event):
    with db:
        db.execute("INSERT OR IGNORE INTO events (id, level) VALUES (?, ?)", (event.key, event.level))


def deliver(db, sender):
    # Serialize send + receipt across watcher processes using the same store.
    with db:
        db.execute("BEGIN IMMEDIATE")
        due, attempts = db.execute("SELECT due, attempts FROM delivery WHERE id=1").fetchone()
        if due > time.time():
            return
        event = db.execute("SELECT id, level FROM events WHERE sent=0 ORDER BY rowid LIMIT 1").fetchone()
        if event is None:
            return
        key, level = event
        try:
            sender(level)
        except Retry as error:
            delay = max(error.delay, min(300, 2 ** min(attempts + 1, 9)))
            db.execute("UPDATE delivery SET attempts=attempts+1, due=? WHERE id=1", (time.time() + delay,))
            print(f"Discord delivery deferred for {delay:g}s.", flush=True)
            return
        db.execute("UPDATE events SET sent=1 WHERE id=?", (key,))
        db.execute("UPDATE delivery SET due=0, attempts=0 WHERE id=1")
    print(f"Posted level {level}.", flush=True)


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path, help="WoW Forever Screenshots directory")
    parser.add_argument("--send", action="store_true", help="enable Discord delivery")
    parser.add_argument("--state", type=Path, help="live SQLite state, one per folder and channel")
    args = parser.parse_args()
    if not args.folder.is_dir():
        parser.error("Screenshots directory missing. Take a screenshot in WoW to create it.")
    db = None
    since = time.time_ns()
    try:
        if args.send:
            secret = os.environ.get("DISCORD_WEBHOOK")
            if not secret:
                if not sys.stdin.isatty():
                    parser.error("Run --send in a terminal or supply DISCORD_WEBHOOK through the environment.")
                secret = getpass.getpass("Discord webhook (hidden): ")
            endpoint = webhook_path(secret)
            root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "state")
            db = open_store(args.state or root / "WoWDing" / "events.db")
            since = db.execute("SELECT since_ns FROM meta WHERE id=1").fetchone()[0]
        scan = Scanner(args.folder, since)

        def accept(event):
            if event.test:
                print(f"Test marker decoded: level {event.level}.", flush=True)
            elif db is None:
                print(f"Dry run: level {event.level}.", flush=True)
            else:
                enqueue(db, event)

        print("Watching for level-ups. " + ("Discord enabled." if db else "Dry run."), flush=True)
        while True:
            scan.scan(accept)
            if db is not None:
                deliver(db, lambda level: post(endpoint, level))
            time.sleep(1)
    finally:
        if db is not None:
            db.close()


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        pass
    except (Rejected, ValueError) as error:
        sys.exit(str(error))
    except (OSError, sqlite3.Error, EOFError):
        sys.exit("Could not access input, the screenshot folder, or the local state. Check access and restart.")
