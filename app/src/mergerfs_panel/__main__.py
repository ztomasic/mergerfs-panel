"""Entry point for ``mergerfs-panel``."""

from __future__ import annotations

import argparse
import sys

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import GLib

from . import __version__
from .ui import APP_NAME, MergerfsApp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mergerfs-panel",
        description="Manage disks and mergerfs pools with drag and drop.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    arguments = parser.parse_args(argv)

    GLib.set_prgname("mergerfs-panel")
    GLib.set_application_name(APP_NAME)

    app = MergerfsApp(self_test=arguments.self_test)
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    raise SystemExit(main())
