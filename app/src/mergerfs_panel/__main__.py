"""Entry point for ``mergerfs-panel``."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .boot import DEFAULT_WAIT


def _log(message: str) -> None:
    print(f"mergerfs-panel: {message}", file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mergerfs-panel",
        description="Manage disks and mergerfs pools with drag and drop.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--restore-pools",
        action="store_true",
        help="mount configured pools and exit (used by the boot service)",
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=DEFAULT_WAIT,
        metavar="SECONDS",
        help=f"with --restore-pools, wait this long for branch disks (default: {DEFAULT_WAIT})",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    arguments = parser.parse_args(argv)

    if arguments.restore_pools:
        from .boot import restore_pools

        return restore_pools(wait_seconds=arguments.wait, log=_log)

    import gi

    gi.require_version("Gtk", "4.0")

    from gi.repository import GLib

    from .ui import APP_NAME, MergerfsApp

    GLib.set_prgname("mergerfs-panel")
    GLib.set_application_name(APP_NAME)

    app = MergerfsApp(self_test=arguments.self_test)
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    raise SystemExit(main())
