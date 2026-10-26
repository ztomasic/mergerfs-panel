# Development

## Setup

Fedora:

```bash
sudo dnf install python3-gobject gtk4
```

Debian / Ubuntu:

```bash
sudo apt install python3-gi gir1.2-gtk-4.0
```

mergerfs is only required for the live tests and for creating pools. Install the
upstream package if you want the full test suite to run.

## Run from the source tree

```bash
make run
# or
PYTHONPATH=app/src python3 -m mergerfs_panel
```

## Tests

```bash
make test
```

The suite covers:

- mountinfo parsing, including octal escapes;
- branch designation parsing and serialization;
- path validation (self, ancestor, descendant, duplicate, `/`, missing);
- config persistence and autostart filtering;
- a **live mergerfs pool** in `/tmp`: mount, add a branch, write a file, remove the
  branch, unmount (skipped when mergerfs or FUSE is unavailable);
- UDisks2 enumeration (skipped when the system bus or udisks2 is unavailable).

The live tests never touch real disks; they use temporary directories and clean up in
`tearDown`. If a test fails midway, check for leftover mounts under `/tmp/mfp-*` and
unmount them manually.

## GUI smoke test

```bash
make self-test
```

This constructs the window, performs one refresh, prints a line, and exits. It is the
fastest way to catch import errors, broken GTK API use, or config failures. It needs a
display because GTK initializes a window.

## Debug logging

```bash
MFP_DEBUG=1 PYTHONPATH=app/src python3 -m mergerfs_panel
```

Logs refresh start/end, counts, and errors to stderr. The `_debug` helper is the only
logging mechanism; keep it cheap and side-effect free.

## Visual checks without a compositor

On Wayland, an occluded window stops receiving frame callbacks and later widget
changes are not laid out until it becomes visible. For automated verification you can
render the widget tree to a PNG inside the process:

```python
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gsk", "4.0")
from gi.repository import Gtk, Gsk, GLib
from mergerfs_panel.ui import MainWindow
from mergerfs_panel.config import Config

app = Gtk.Application(application_id="org.mergerfs.Panel.Snapshot")

def capture(win, path):
    root = win.get_child()
    paintable = Gtk.WidgetPaintable.new(root)
    snapshot = Gtk.Snapshot()
    paintable.snapshot(snapshot, root.get_width(), root.get_height())
    renderer = Gsk.CairoRenderer.new()
    renderer.realize()
    renderer.render_texture(snapshot.to_node(), None).save_to_png(path)

def on_activate(a):
    win = MainWindow(a, Config())
    win.present()
    def snap():
        capture(win, "/tmp/mergerfs-panel.png")
        a.quit()
        return False
    GLib.timeout_add(3000, snap)

app.connect("activate", on_activate)
app.run([])
```

Run it with `GDK_BACKEND=x11` when the session is locked; the X11 frame clock does not
depend on compositor callbacks.

## Code map

| File | Notes |
|---|---|
| `backend.py` | No GTK at import time; everything here is testable |
| `config.py` | Disk format; atomic writes; no GTK |
| `ui.py` | GTK objects, DnD payloads, confirmations |
| `__main__.py` | Entry point; `--self-test` is hidden from `--help` |

Conventions:

- Standard library plus PyGObject only; do not add runtime dependencies without
  discussion.
- Type hints on public functions. Keep user-facing messages actionable.
- Blocking work goes through `run_async` and returns to the UI with `GLib.idle_add`.
- Destructive actions require confirmation; adding a branch does not.
- Validate paths before writing an xattr; read the branch list back after each write.
- Keep the UI usable without drag and drop: every gesture needs a button.

## Adding a backend operation

1. Add the function to `backend.py` with a docstring and a `MergerfsError` /
   `UDisksError` failure mode.
2. Add a unit test, ideally a live one guarded by `mergerfs_available()`.
3. Wire it in `ui.py` through `run_async`, with a status message and an error dialog.

## Changing the branch protocol

The xattr grammar is defined by mergerfs, not by this project. Table of verified
forms is in [ARCHITECTURE.md](ARCHITECTURE.md#branch-protocol). Remember that
`-[...]` from the upstream documentation is rejected; the working removal form is
`-/path`. Always verify a write by reading the list back.

## Packaging changes

See [PACKAGING.md](PACKAGING.md). After changing `pyproject.toml` or `data/`, rebuild
the tarball and at least the Fedora package; the universal installer is a quick way
to check the installed layout without building a package.

## CI

`.github/workflows/ci.yml` runs the tests, validates the desktop entry, and builds a
wheel on Ubuntu. The live mergerfs tests run when the runner has `/dev/fuse` and the
`mergerfs` package is available; otherwise they skip. Do not make CI depend on a
specific desktop session.
