#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p dist
build=$(mktemp -d "${TMPDIR:-/tmp}/wow-ding-build.XXXXXX")
trap 'rm -rf "$build"' EXIT
app="$build/WoW Ding.app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
cp macos/Info.plist "$app/Contents/"
cp -R Ding "$app/Contents/Resources/"
for arch in arm64 x86_64; do
    xcrun swiftc -swift-version 5 -O -whole-module-optimization -parse-as-library \
        -target "${arch}-apple-macos13.0" -module-cache-path "$build/modules" \
        macos/*.swift -o "$build/$arch"
done
lipo -create "$build/arm64" "$build/x86_64" -output "$app/Contents/MacOS/WoWDing"
codesign --force --sign "${CODESIGN_IDENTITY:--}" --options runtime "$app"
codesign --verify --deep --strict "$app"
ditto -c -k --keepParent "$app" "$build/WoW-Ding-macOS.zip"
ditto "$app" "dist/WoW Ding.app"
mv "$build/WoW-Ding-macOS.zip" dist/
echo "Built dist/WoW Ding.app and dist/WoW-Ding-macOS.zip"
