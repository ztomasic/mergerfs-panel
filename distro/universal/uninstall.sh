#!/usr/bin/env bash
set -euo pipefail

PREFIX="${PREFIX:-/usr/local}"
DESTDIR="${DESTDIR:-}"

rm -f "$DESTDIR$PREFIX/bin/mergerfs-panel"
rm -rf "$DESTDIR$PREFIX/lib/mergerfs-panel"
rm -f "$DESTDIR$PREFIX/share/applications/mergerfs-panel.desktop"
rm -f "$DESTDIR$PREFIX/share/icons/hicolor/scalable/apps/mergerfs-panel.svg"
rm -f "$DESTDIR$PREFIX/share/metainfo/mergerfs-panel.metainfo.xml"

if [ -z "$DESTDIR" ]; then
    command -v update-desktop-database >/dev/null 2>&1 &&
        update-desktop-database -q "$DESTDIR$PREFIX/share/applications" || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 &&
        gtk-update-icon-cache -q -t "$DESTDIR$PREFIX/share/icons/hicolor" || true
fi

echo "Removed mergerfs-panel from $PREFIX"
