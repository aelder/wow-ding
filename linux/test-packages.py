"""Run in a disposable Linux desktop session with an unlocked test keyring."""
import argparse
import contextlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import select
import socket
import ssl
import shutil
import subprocess
import sys
import tempfile
import time
import threading
import tkinter as tk

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from test_ding import Addon


def wait_for(check, description):
    for _ in range(100):
        if check():
            return
        time.sleep(0.1)
    raise RuntimeError("Timed out waiting for " + description)


@contextlib.contextmanager
def running(args):
    with subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, bufsize=0) as process:
        try:
            yield process
        finally:
            process.terminate()
            process.wait(timeout=5)


def output_until(process, expected):
    buffer = b""
    end = time.monotonic() + 15
    while expected not in buffer:
        if time.monotonic() > end or not select.select([process.stdout], [], [], 1)[0]:
            if time.monotonic() > end:
                raise AssertionError(f"Timed out waiting for {expected!r}, got {buffer!r}")
            continue
        part = os.read(process.stdout.fileno(), 4096)
        if not part:
            raise AssertionError(f"Process exited before {expected!r}, got {buffer!r}")
        buffer += part


def verify(binary, root):
    os.environ.update(XDG_STATE_HOME=str(root / "state"), XDG_CONFIG_HOME=str(root / "config"))
    import linux_app as app
    # The command and source setup must share this fixture's config paths.
    app.CONFIG = root / "config/wow-ding/settings.json"
    app.AUTOSTART = root / "config/autostart/wow-ding.desktop"
    app.STATE = root / "state/wow-ding"
    game = root / "Wine prefix/drive_c/Games/World of Warcraft/_forever_"
    game.mkdir(parents=True)
    (game / "Wow.exe").touch()
    token = "https://discord.com/api/webhooks/123/offline-fixture"
    shots = game / "Screenshots"
    control = tk.Tk(className="TestController")
    control.withdraw()
    try:
        with running([binary]) as gui:
            def visible():
                if gui.poll() is not None:
                    raise RuntimeError(gui.stdout.read().decode())
                return subprocess.run(["xdotool", "search", "--onlyvisible", "--name", "^WoW Ding$"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
            wait_for(visible, "setup window")
            app_name = next(name for name in control.winfo_interps() if name != control.tk.call("tk", "appname"))
            # Exercise the same Tk controls as a player, using the isolated X server.
            def remote(*args):
                return control.tk.call("send", app_name, args)
            frame = ".!frame"
            remote(frame + ".!entry", "insert", 0, str(game.parent))
            remote(frame + ".!entry2", "insert", 0, token)
            remote(frame + ".!frame.!button", "invoke")
            wait_for(lambda: (app.STATE / "status").exists(), "connected watcher")
            assert (game / "Interface/AddOns/Ding/Ding.lua").read_bytes() == (ROOT / "Ding/Ding.lua").read_bytes()
            subprocess.run(["desktop-file-validate", app.AUTOSTART], check=True)
            assert app.credential("lookup", "123") == token
            assert token not in app.CONFIG.read_text()
            subprocess.run([binary, "--watch"], check=True, timeout=8)
            # Close setup; the detached watcher must still receive a new capture.
            remote("destroy", ".")
            assert gui.wait(timeout=5) == 0
        Addon().capture(ping=True).save(shots / "WoWScrnShot-ping.jpg")
        wait_for(lambda: len(messages) == 1, "confirmed test ding")
        assert messages.pop() == {"content": "Test ding! Élara is level 17 in WoW.", "allowed_mentions": {"parse": []}}
        subprocess.run([binary, "--disconnect"], check=True, timeout=10)
    finally:
        control.destroy()
    assert not app.CONFIG.exists() and not app.AUTOSTART.exists()
    assert not (game / "Interface/AddOns/Ding/Ding.lua").exists()
    assert subprocess.run(["secret-tool", "lookup", "application", "org.wow-ding.linux", "channel", "123"],
                          capture_output=True).returncode != 0
    with running([binary, "--dry-run", shots]) as dry:
        output_until(dry, b"Dry run.")
        Addon().capture(42).save(shots / "WoWScrnShot.jpg")
        output_until(dry, "Dry run: Élara, level 42".encode())
    print(f"Passed installed GUI, keyring watcher, disconnect and screenshot dry run for {binary}", flush=True)


messages = []


class DiscordFixture(BaseHTTPRequestHandler):
    def do_GET(self):
        assert self.path == "/api/webhooks/123/offline-fixture"
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"channel_id":"123"}')

    def do_POST(self):
        assert self.path == "/api/webhooks/123/offline-fixture?wait=true"
        messages.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"id":"fixture"}')

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installed-only", action="store_true", help="test the system package only")
    args = parser.parse_args()
    if socket.gethostbyname("discord.com") != "127.0.0.1":
        sys.exit("Run inside the offline test container with discord.com mapped to loopback.")
    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp)
        cert, key = directory / "cert.pem", directory / "key.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                        "-keyout", key, "-out", cert, "-subj", "/CN=discord.com",
                        "-addext", "subjectAltName=DNS:discord.com"], stderr=subprocess.DEVNULL, check=True)
        os.environ["SSL_CERT_FILE"] = str(cert)
        with ThreadingHTTPServer(("127.0.0.1", 443), DiscordFixture) as server:
            tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            tls.load_cert_chain(cert, key)
            server.socket = tls.wrap_socket(server.socket, server_side=True)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                verify("/usr/bin/wow-ding", directory / "installed")
                if not args.installed_only:
                    subprocess.run(["tar", "-xzf", ROOT / "dist/WoW-Ding-Linux-x86_64.tar.gz", "-C", directory], check=True)
                    portable = directory / 'Portable $ WoW'
                    shutil.move(directory / "wow-ding", portable)
                    verify(str(portable / "wow-ding"), directory / "portable-test")
            finally:
                server.shutdown()
