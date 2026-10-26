#!/usr/bin/env bash
#
# Distribution-independent installer.
#
#   sudo ./distro/universal/install.sh                 # install to /usr/local
#   PREFIX=$HOME/.local ./distro/universal/install.sh  # install for one user
#   DESTDIR=/tmp/pkg PREFIX=/usr ./install.sh          # stage a package tree
#
set -euo pipefail

PREFIX="${PREFIX:-/usr/local}"
DESTDIR="${DESTDIR:-}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$HERE/../../app"

BINDIR="$DESTDIR$PREFIX/bin"
LIBDIR="$DESTDIR$PREFIX/lib/mergerfs-panel"
PKGDIR="$LIBDIR/mergerfs_panel"
APPDIR="$DESTDIR$PREFIX/share/applications"
ICONDIR="$DESTDIR$PREFIX/share/icons/hicolor/scalable/apps"
METAINFODIR="$DESTDIR$PREFIX/share/metainfo"

if ! python3 - <<'PY'
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: F401
PY
then
    echo "error: PyGObject with GTK 4 is required." >&2
    echo "  Fedora:  sudo dnf install python3-gobject gtk4" >&2
    echo "  Debian:  sudo apt install python3-gi gir1.2-gtk-4.0" >&2
    echo "  Arch:    sudo pacman -S python-gobject gtk4" >&2
    exit 1
fi

if ! command -v mergerfs >/dev/null 2>&1; then
    echo "note: mergerfs is not installed; the app can still list disks and pools," >&2
    echo "      but creating new pools needs it: https://github.com/trapexit/mergerfs/releases" >&2
fi

install -d "$BINDIR" "$PKGDIR" "$APPDIR" "$ICONDIR" "$METAINFODIR"
install -m 644 "$SOURCE"/src/mergerfs_panel/*.py "$PKGDIR"/
install -m 644 "$SOURCE"/data/mergerfs-panel.desktop "$APPDIR"/
install -m 644 "$SOURCE"/data/mergerfs-panel.svg "$ICONDIR"/
install -m 644 "$SOURCE"/data/mergerfs-panel.metainfo.xml "$METAINFODIR"/

cat > "$BINDIR/mergerfs-panel" <<EOF
#!/bin/sh
PYTHONPATH="$PREFIX/lib/mergerfs-panel\${PYTHONPATH:+:\$PYTHONPATH}"
export PYTHONPATH
exec python3 -m mergerfs_panel "\$@"
EOF
chmod 755 "$BINDIR/mergerfs-panel"

if [ -z "$DESTDIR" ]; then
    command -v update-desktop-database >/dev/null 2>&1 &&
        update-desktop-database -q "$APPDIR" || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 &&
        gtk-update-icon-cache -q -t "$DESTDIR$PREFIX/share/icons/hicolor" || true
fi

echo "Installed to $PREFIX/bin/mergerfs-panel"
case ":$PATH:" in
    *":$PREFIX/bin:"*) ;;
    *) echo "note: $PREFIX/bin is not in PATH" >&2 ;;
esac
