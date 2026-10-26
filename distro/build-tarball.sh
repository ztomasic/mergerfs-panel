#!/usr/bin/env bash
# Build the source tarball consumed by the Fedora, Debian and Arch packages.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="mergerfs-panel"
VERSION="$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$ROOT/app/pyproject.toml" | head -n1)"
if [ -z "$VERSION" ]; then
    echo "error: could not read project version from app/pyproject.toml" >&2
    exit 1
fi

OUT_DIR="${1:-$ROOT/dist}"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$STAGE/$NAME-$VERSION"
cp -a "$ROOT/app/." "$STAGE/$NAME-$VERSION/"
if [ -f "$ROOT/README.md" ]; then
    cp "$ROOT/README.md" "$STAGE/$NAME-$VERSION/"
fi
if [ -d "$ROOT/docs" ]; then
    cp -a "$ROOT/docs" "$STAGE/$NAME-$VERSION/"
fi

find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$STAGE" -name '*.pyc' -delete
find "$STAGE" \( -name build -o -name '*.egg-info' \) -prune -exec rm -rf {} +

mkdir -p "$OUT_DIR"
TARBALL="$OUT_DIR/$NAME-$VERSION.tar.gz"
tar -C "$STAGE" --owner=0 --group=0 -czf "$TARBALL" "$NAME-$VERSION"
echo "$TARBALL"
