"""Install and remove the two addon files managed by WoW Ding."""
import hashlib
import os
from pathlib import Path
import tempfile

SOURCE = Path(__file__).resolve().parent / "Ding"
FILES = ("Ding.toc", "Ding.lua")


def forever(path):
    parent = Path(path)
    for game in (parent, parent / "_forever_"):
        if game.name.lower() == "_forever_" and (game / "Wow.exe").is_file():
            return game.resolve()
    raise ValueError("Select the _forever_ folder containing Wow.exe, or its World of Warcraft parent.")


def detect():
    import winreg

    candidates = []
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\Blizzard Entertainment\World of Warcraft",
                                    0, winreg.KEY_READ | view) as key:
                    install = Path(winreg.QueryValueEx(key, "InstallPath")[0])
                    candidates.extend((install, install.parent))
            except OSError:
                pass
    for var in ("ProgramFiles(x86)", "ProgramFiles"):
        if os.environ.get(var):
            candidates.append(Path(os.environ[var]) / "World of Warcraft")
    for candidate in candidates:
        try:
            return forever(candidate)
        except (ValueError, OSError):
            pass
    return None


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_file(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temp:
        scratch = Path(temp.name)
        try:
            temp.write(data)
            temp.close()
            scratch.replace(path)
        finally:
            scratch.unlink(missing_ok=True)


def addon_dir(game):
    folder = game / "Interface" / "AddOns" / "Ding"
    if not folder.resolve().is_relative_to(game.resolve()):
        raise ValueError("The Ding addon folder points outside this WoW installation.")
    return folder


def install_addon(game, previous):
    folder = addon_dir(game)
    folder.mkdir(parents=True, exist_ok=True)
    payload = {name: (SOURCE / name).read_bytes() for name in FILES}
    for name, data in payload.items():
        path = folder / name
        if path.exists():
            existing = path.read_bytes()
            if existing != data and digest(existing) != previous.get(name):
                raise ValueError("Ding already has different addon files. Back up and move its folder, then retry.")
    for name, data in payload.items():
        write_file(folder / name, data)
    return {name: digest(data) for name, data in payload.items()}


def remove_addon(config):
    game = Path(config["game"])
    if game.name.lower() != "_forever_":
        return
    folder = addon_dir(game)
    for name in FILES:
        target = folder / name
        if target.is_file() and digest(target.read_bytes()) == config["files"].get(name):
            target.unlink()
    if folder.exists() and not any(folder.iterdir()):
        folder.rmdir()
