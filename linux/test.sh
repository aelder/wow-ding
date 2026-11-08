#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
python -m unittest discover -s tests -v
dpkg -i dist/WoW-Ding-Linux.deb
# Run only in the disposable build container. A private session provides
# a real Secret Service keyring and X display for both packaged entry points.
runtime=$(mktemp -d)
trap 'rm -rf "$runtime"' EXIT
mkdir -m 700 "$runtime/session"
XDG_RUNTIME_DIR="$runtime/session" XDG_DATA_HOME="$runtime/data" dbus-run-session -- xvfb-run -a sh -ec '
    printf "%s" fixture-password | gnome-keyring-daemon --unlock --components=secrets
    python linux/test-packages.py
'
