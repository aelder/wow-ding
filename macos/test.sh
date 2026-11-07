#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
scratch=$(mktemp -d "${TMPDIR:-/tmp}/wow-ding-test.XXXXXX")
trap 'rm -rf "$scratch"' EXIT
python3 -m unittest discover -s tests -v
python3 macos/Tests/fixtures.py "$scratch"
xcrun swiftc -swift-version 5 -parse-as-library -module-cache-path "$scratch/modules" \
    macos/{Marker,Storage,Connection}.swift macos/Tests/Integration.swift -o "$scratch/check"
"$scratch/check" "$scratch"
