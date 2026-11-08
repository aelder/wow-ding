#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
[ "$(uname -sm)" = "Linux x86_64" ] || { echo "Build the portable release on x86-64 Linux." >&2; exit 1; }
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p dist
deb="$work/deb"
app="$deb/usr/share/wow-ding"
mkdir -p "$deb/DEBIAN" "$deb/usr/bin" "$deb/usr/share/applications" "$app"
cp -R Ding addon.py hook.py marker.py watch.py linux_app.py linux_ui.py "$app/"
printf '%s\n' '#!/bin/sh' 'exec /usr/bin/python3 /usr/share/wow-ding/linux_app.py "$@"' > "$deb/usr/bin/wow-ding"
chmod 755 "$deb/usr/bin/wow-ding"
install -m 644 linux/wow-ding.desktop "$deb/usr/share/applications/"
desktop-file-validate "$deb/usr/share/applications/wow-ding.desktop"
cat > "$deb/DEBIAN/control" <<'CONTROL'
Package: wow-ding
Version: 1.4.0
Architecture: all
Maintainer: WoW Ding contributors <aelder@users.noreply.github.com>
Section: games
Priority: optional
Depends: python3 (>= 3.10), python3-pil, python3-tk, libsecret-tools, ca-certificates
Recommends: default-dbus-session-bus | dbus-session-bus, gnome-keyring | org.freedesktop.secrets
Homepage: https://github.com/aelder/wow-ding
Description: WoW Forever level-up notifications for Discord
 Watches local Wine or Proton screenshots and posts the character and level.
CONTROL
dpkg-deb --root-owner-group --build "$deb" "$work/WoW-Ding-Linux.deb"
python -m PyInstaller --noconfirm --onedir --name wow-ding --add-data "$PWD/Ding:Ding" \
    --workpath "$work/build" --specpath "$work" --distpath "$work/portable" linux_app.py
cp README.md "$work/portable/wow-ding/"
tar -C "$work/portable" -czf "$work/WoW-Ding-Linux-x86_64.tar.gz" wow-ding
mv "$work/WoW-Ding-Linux.deb" "$work/WoW-Ding-Linux-x86_64.tar.gz" dist/
