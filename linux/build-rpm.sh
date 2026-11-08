#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
spec=linux/wow-ding.spec
version=$(rpmspec -q --srpm --qf '%{version}' "$spec")
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/SOURCES" dist
git archive --format=tar.gz --prefix="wow-ding-$version/" \
    -o "$work/SOURCES/wow-ding-$version.tar.gz" "v$version"
rpmbuild --define "_topdir $work" -bb "$spec"
cp "$work"/RPMS/noarch/wow-ding-*.noarch.rpm dist/WoW-Ding-Linux.rpm
