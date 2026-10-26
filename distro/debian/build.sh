#!/usr/bin/env bash
# Build a Debian package from the source tarball.
#
#   sudo apt install debhelper dh-python python3-all python3-setuptools
#   ./distro/debian/build.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$ROOT/app/pyproject.toml" | head -n1)"
TARBALL="$ROOT/dist/mergerfs-panel-$VERSION.tar.gz"
[ -f "$TARBALL" ] || "$ROOT/distro/build-tarball.sh" >/dev/null

if ! command -v dpkg-buildpackage >/dev/null 2>&1; then
    echo "error: dpkg-buildpackage not found; install debhelper, dpkg-dev and dh-python" >&2
    exit 1
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
tar -C "$WORK" -xzf "$TARBALL"
cp -a "$ROOT/distro/debian" "$WORK/mergerfs-panel-$VERSION/debian"
chmod 755 "$WORK/mergerfs-panel-$VERSION/debian/rules"

(
    cd "$WORK/mergerfs-panel-$VERSION"
    dpkg-buildpackage -us -uc -b
)
mkdir -p "$ROOT/dist"
cp "$WORK"/*.deb "$ROOT/dist/" 2>/dev/null || true
ls -1 "$ROOT/dist"/*.deb 2>/dev/null || echo "no .deb produced" >&2
