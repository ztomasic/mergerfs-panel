"""GTK4 user interface: a disks panel and a mergerfs pools panel.

Drag a disk row onto a pool card to add it as a live branch; drag a branch
or a pool onto the disks panel to remove it / unmount it. Every gesture has
a button equivalent so the app stays usable without drag and drop.
"""

from __future__ import annotations

import json
import os
import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Pango

from . import backend
from .config import Config

APP_ID = "org.mergerfs.Panel"
APP_NAME = "MergerFS Panel"

CSS = """
.panel-header {
    padding: 10px 14px 6px 14px;
}
.panel-title {
    font-weight: 700;
    font-size: 1.05em;
}
.column-header {
    padding: 6px 14px;
    background-color: alpha(currentColor, 0.05);
}
.dim {
    opacity: 0.65;
    font-size: 0.9em;
}
.mono {
    font-family: monospace;
    font-size: 0.92em;
}
.list-row {
    padding: 8px 10px;
    border-bottom: 1px solid alpha(currentColor, 0.08);
}
.pool-card {
    border: 1px solid alpha(currentColor, 0.15);
    border-radius: 12px;
    padding: 8px;
    margin: 6px 8px;
}
.pool-title {
    font-weight: 700;
}
.drag-over {
    outline: 2px dashed #3584e4;
    outline-offset: -2px;
}
.empty-state {
    padding: 24px;
}
"""


def human_size(size: int) -> str:
    if not size:
        return "—"
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    value = float(size)
    index = 0
    while value >= 1000 and index < len(units) - 1:
        value /= 1000
        index += 1
    if index == 0:
        return f"{int(value)} B"
    return f"{value:.1f} {units[index]}"


def _debug(message: str) -> None:
    if os.environ.get("MFP_DEBUG"):
        print(f"mergerfs-panel: {message}", file=sys.stderr, flush=True)


def run_async(work, on_success, on_error):
    """Run *work* off the UI thread and deliver the result on it."""

    def runner():
        try:
            result = work()
        except Exception as exc:  # noqa: BLE001 - the message is shown to the user
            GLib.idle_add(on_error, exc)
        else:
            GLib.idle_add(on_success, result)

    threading.Thread(target=runner, daemon=True).start()


def clear_box(box: Gtk.Box) -> None:
    child = box.get_first_child()
    while child is not None:
        following = child.get_next_sibling()
        box.remove(child)
        child = following


def decode_payload(value) -> dict | None:
    if isinstance(value, GObject.Value):
        try:
            value = value.get_string()
        except (TypeError, AttributeError):
            return None
    if not isinstance(value, str):
        return None
    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, application: Gtk.Application, config: Config, self_test: bool = False) -> None:
        super().__init__(application=application, title=APP_NAME)
        self.config = config
        self.self_test = self_test
        self.udisks: backend.UDisks | None = None
        self.udisks_error: str | None = None
        self.disks: list[backend.Disk] = []
        self.pools: list[backend.Pool] = []
        self._refreshing = False

        self.set_default_size(1180, 720)
        self._apply_css()
        self._build()

        try:
            self.udisks = backend.UDisks()
        except Exception as exc:  # noqa: BLE001
            self.udisks_error = str(exc)

        self.refresh()
        self._autostart_pools()

    # -- construction ------------------------------------------------------

    def _apply_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode("utf-8"))
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def _build(self) -> None:
        header = Gtk.HeaderBar()
        self.set_titlebar(header)

        refresh_button = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh_button.set_tooltip_text("Reload disks, pools and branches")
        refresh_button.connect("clicked", lambda *_: self.refresh())
        header.pack_start(refresh_button)

        new_pool_button = Gtk.Button(label="New pool")
        new_pool_button.add_css_class("suggested-action")
        new_pool_button.set_tooltip_text("Create a mergerfs pool from a mounted disk")
        new_pool_button.connect("clicked", lambda *_: self._new_pool_dialog())
        header.pack_end(new_pool_button)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(root)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(560)
        paned.set_hexpand(True)
        paned.set_vexpand(True)
        paned.set_resize_start_child(True)
        paned.set_resize_end_child(True)
        root.append(paned)

        paned.set_start_child(self._build_disks_panel())
        paned.set_end_child(self._build_pools_panel())

        self.status_label = Gtk.Label(label="", xalign=0)
        self.status_label.add_css_class("dim")
        status_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        status_bar.set_margin_start(14)
        status_bar.set_margin_end(14)
        status_bar.set_margin_top(4)
        status_bar.set_margin_bottom(8)
        status_bar.append(self.status_label)
        root.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        root.append(status_bar)

    def _panel_shell(self, title: str, subtitle: str, drop_handler):
        shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        shell.add_css_class("panel")

        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        header.add_css_class("panel-header")
        title_label = Gtk.Label(label=title, xalign=0)
        title_label.add_css_class("panel-title")
        subtitle_label = Gtk.Label(label=subtitle, xalign=0)
        subtitle_label.add_css_class("dim")
        subtitle_label.set_wrap(True)
        header.append(title_label)
        header.append(subtitle_label)
        shell.append(header)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        shell.append(scrolled)

        target = Gtk.DropTarget.new(
            GObject.TYPE_STRING, Gdk.DragAction.COPY | Gdk.DragAction.MOVE
        )
        target.connect("drop", drop_handler)
        target.connect("enter", self._on_drag_enter, shell)
        target.connect("leave", self._on_drag_leave, shell)
        shell.add_controller(target)

        return shell, scrolled

    def _build_disks_panel(self):
        shell, scrolled = self._panel_shell(
            "Disks",
            "Filesystems on this machine. Drag one onto a pool to add it as a branch, "
            "or use the buttons.",
            self._on_disks_drop,
        )
        self.disks_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        scrolled.set_child(self.disks_box)
        return shell

    def _build_pools_panel(self):
        shell, scrolled = self._panel_shell(
            "mergerfs pools",
            "Drop a disk here to add a branch. Drag a pool or branch to the disks panel "
            "to unmount it or remove it.",
            self._on_pools_drop,
        )
        self.pools_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        scrolled.set_child(self.pools_box)
        return shell

    # -- drag plumbing -----------------------------------------------------

    def _on_drag_enter(self, target, x, y, widget):
        widget.add_css_class("drag-over")
        return Gdk.DragAction.COPY | Gdk.DragAction.MOVE

    def _on_drag_leave(self, target, widget):
        widget.remove_css_class("drag-over")

    def _provider(self, payload: dict):
        return Gdk.ContentProvider.new_for_value(json.dumps(payload))

    def _prepare_disk_drag(self, source, x, y, disk: backend.Disk):
        payload = {
            "kind": "disk",
            "device": disk.device,
            "object_path": disk.object_path,
            "mountpoints": disk.mountpoints,
        }
        return self._provider(payload)

    def _prepare_branch_drag(self, source, x, y, pool: backend.Pool, branch: backend.Branch):
        return self._provider({"kind": "branch", "pool": pool.mountpoint, "path": branch.path})

    def _prepare_pool_drag(self, source, x, y, pool: backend.Pool):
        return self._provider({"kind": "pool", "mountpoint": pool.mountpoint})

    def _on_disks_drop(self, target, value, x, y):
        payload = decode_payload(value)
        if payload is None:
            return False
        if payload.get("kind") == "branch":
            self._confirm_remove_branch(payload.get("pool", ""), payload.get("path", ""))
            return True
        if payload.get("kind") == "pool":
            self._confirm_unmount_pool(payload.get("mountpoint", ""))
            return True
        return False

    def _on_pools_drop(self, target, value, x, y):
        payload = decode_payload(value)
        if payload is None or payload.get("kind") != "disk":
            return False
        mountpoints = [point for point in payload.get("mountpoints") or [] if point]
        if mountpoints:
            self._new_pool_dialog(preset_branch=mountpoints[0])
        else:
            self._mount_for_new_pool(payload)
        return True

    def _on_pool_drop(self, target, value, x, y, pool: backend.Pool):
        payload = decode_payload(value)
        if payload is None or payload.get("kind") != "disk":
            return False
        self._add_disk_to_pool(payload, pool)
        return True

    # -- rendering ---------------------------------------------------------

    def refresh(self) -> None:
        if self._refreshing:
            _debug("refresh skipped: already running")
            return
        self._refreshing = True
        _debug("refresh started")

        def work():
            pools = backend.list_pools()
            disks: list[backend.Disk] = []
            error = None
            try:
                if self.udisks is None:
                    self.udisks = backend.UDisks()
                disks = self.udisks.list_disks()
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
            _debug(f"refresh work done: pools={len(pools)} disks={len(disks)} error={error}")
            return pools, disks, error

        run_async(work, self._apply_refresh, self._refresh_error)

    def _refresh_error(self, exc: Exception) -> None:
        self._refreshing = False
        self._set_status(f"Refresh failed: {exc}")

    def _apply_refresh(self, result) -> None:
        self.pools, self.disks, error = result
        self._render_disks()
        self._render_pools()
        _debug(
            f"applied: pools={len(self.pools)} disks={len(self.disks)} "
            f"disk_rows={self.disks_box.get_first_child() is not None}"
        )
        if error:
            self._set_status(f"UDisks2 unavailable: {error}")
        elif self.udisks_error:
            self._set_status(f"UDisks2 unavailable: {self.udisks_error}")
        self._refreshing = False

    def _render_disks(self) -> None:
        clear_box(self.disks_box)
        if not self.disks:
            empty = Gtk.Label(label="No filesystems found")
            empty.add_css_class("dim")
            empty.add_css_class("empty-state")
            self.disks_box.append(empty)
            return
        for disk in self.disks:
            self.disks_box.append(self._disk_row(disk))

    def _disk_row(self, disk: backend.Disk) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add_css_class("list-row")
        row.set_tooltip_text(
            "Drag onto a pool to add as a branch"
            if disk.mounted
            else "Drag onto a pool: the disk is mounted first"
        )

        icon = Gtk.Image.new_from_icon_name("drive-harddisk-symbolic")
        icon.set_pixel_size(22)
        row.append(icon)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text.set_hexpand(True)
        name = Gtk.Label(label=disk.display_name, xalign=0)
        name.set_ellipsize(Pango.EllipsizeMode.END)
        details = [disk.fs_type, human_size(disk.size)]
        details.append(", ".join(disk.mountpoints) if disk.mountpoints else "not mounted")
        if disk.system:
            details.append("system")
        if disk.removable:
            details.append("removable")
        subtitle = Gtk.Label(label=" · ".join(part for part in details if part), xalign=0)
        subtitle.add_css_class("dim")
        subtitle.set_ellipsize(Pango.EllipsizeMode.END)
        text.append(name)
        text.append(subtitle)
        row.append(text)

        if disk.mounted:
            button = Gtk.Button(label="Unmount")
            button.set_tooltip_text("Unmount this filesystem")
            button.connect("clicked", lambda *_: self._unmount_disk(disk))
        else:
            button = Gtk.Button(label="Mount")
            button.set_tooltip_text("Mount this filesystem with UDisks2")
            button.connect("clicked", lambda *_: self._mount_disk(disk))
        row.append(button)

        source = Gtk.DragSource.new()
        source.set_actions(Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        source.connect("prepare", self._prepare_disk_drag, disk)
        row.add_controller(source)
        return row

    def _render_pools(self) -> None:
        clear_box(self.pools_box)
        if not self.pools:
            empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            empty.add_css_class("empty-state")
            title = Gtk.Label(label="No mergerfs pools mounted")
            title.add_css_class("dim")
            hint = Gtk.Label(
                label="Drag a disk here to create one, or use “New pool”.",
                xalign=0.5,
            )
            hint.add_css_class("dim")
            hint.set_wrap(True)
            empty.append(title)
            empty.append(hint)
            self.pools_box.append(empty)
            return
        for pool in self.pools:
            self.pools_box.append(self._pool_card(pool))

    def _pool_card(self, pool: backend.Pool) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.add_css_class("pool-card")

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        icon = Gtk.Image.new_from_icon_name("drive-multidisk-symbolic")
        icon.set_pixel_size(22)
        header.append(icon)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text.set_hexpand(True)
        title = Gtk.Label(label=pool.mountpoint, xalign=0)
        title.add_css_class("pool-title")
        title.set_ellipsize(Pango.EllipsizeMode.END)
        total, free = backend.usage(pool.mountpoint)
        parts = [f"{len(pool.branches)} branch" + ("es" if len(pool.branches) != 1 else "")]
        if total:
            parts.append(f"{human_size(free)} free of {human_size(total)}")
        if self.config.is_managed(pool.mountpoint):
            parts.append("managed")
        subtitle = Gtk.Label(label=" · ".join(parts), xalign=0)
        subtitle.add_css_class("dim")
        text.append(title)
        text.append(subtitle)
        header.append(text)

        unmount_button = Gtk.Button(icon_name="media-eject-symbolic")
        unmount_button.set_tooltip_text("Unmount this pool")
        unmount_button.connect("clicked", lambda *_: self._confirm_unmount_pool(pool.mountpoint))
        header.append(unmount_button)

        source = Gtk.DragSource.new()
        source.set_actions(Gdk.DragAction.MOVE)
        source.connect("prepare", self._prepare_pool_drag, pool)
        header.add_controller(source)
        card.append(header)

        target = Gtk.DropTarget.new(
            GObject.TYPE_STRING, Gdk.DragAction.COPY | Gdk.DragAction.MOVE
        )
        target.connect("drop", self._on_pool_drop, pool)
        target.connect("enter", self._on_drag_enter, card)
        target.connect("leave", self._on_drag_leave, card)
        card.add_controller(target)

        if not pool.branches:
            missing = Gtk.Label(label="branch list unavailable", xalign=0)
            missing.add_css_class("dim")
            missing.set_margin_start(32)
            card.append(missing)

        for branch in pool.branches:
            card.append(self._branch_row(pool, branch))
        return card

    def _branch_row(self, pool: backend.Pool, branch: backend.Branch) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.add_css_class("list-row")
        row.set_margin_start(26)
        row.set_tooltip_text("Drag onto the disks panel to remove this branch")

        icon = Gtk.Image.new_from_icon_name("folder-symbolic")
        icon.set_pixel_size(16)
        row.append(icon)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text.set_hexpand(True)
        path = Gtk.Label(label=branch.path, xalign=0)
        path.add_css_class("mono")
        path.set_ellipsize(Pango.EllipsizeMode.END)
        total, free = backend.usage(branch.path)
        if total:
            detail_text = f"{human_size(free)} free of {human_size(total)}"
        else:
            detail_text = "unavailable"
        if branch.flags and branch.flags.upper() != "RW":
            detail_text += f" · {branch.flags}"
        detail = Gtk.Label(label=detail_text, xalign=0)
        detail.add_css_class("dim")
        text.append(path)
        text.append(detail)
        row.append(text)

        remove_button = Gtk.Button(icon_name="user-trash-symbolic")
        remove_button.set_tooltip_text("Remove this branch from the pool")
        remove_button.add_css_class("flat")
        remove_button.connect(
            "clicked", lambda *_: self._confirm_remove_branch(pool.mountpoint, branch.path)
        )
        row.append(remove_button)

        source = Gtk.DragSource.new()
        source.set_actions(Gdk.DragAction.MOVE)
        source.connect("prepare", self._prepare_branch_drag, pool, branch)
        row.add_controller(source)
        return row

    # -- actions -----------------------------------------------------------

    def _set_status(self, text: str) -> None:
        self.status_label.set_text(text)

    def _error(self, title: str, detail: str) -> None:
        dialog = Gtk.AlertDialog(message=title, detail=detail, buttons=["Close"])
        dialog.set_modal(True)
        dialog.show(self)

    def _confirm(self, title: str, detail: str, action: str, on_accept) -> None:
        dialog = Gtk.AlertDialog(
            message=title,
            detail=detail,
            buttons=["Cancel", action],
            cancel_button=0,
            default_button=0,
        )
        dialog.set_modal(True)

        def finished(dlg, result):
            try:
                choice = dlg.choose_finish(result)
            except GLib.Error:
                return
            if choice == 1:
                on_accept()

        dialog.choose(self, None, finished)

    def _mount_disk(self, disk: backend.Disk) -> None:
        if self.udisks is None:
            self._error("UDisks2 unavailable", self.udisks_error or "no system bus connection")
            return
        self._set_status(f"Mounting {disk.device}…")

        def done(mountpoint):
            self._set_status(f"Mounted {disk.device} at {mountpoint}")
            self.refresh()

        run_async(
            lambda: self.udisks.mount(disk.object_path),
            done,
            lambda exc: self._error("Mount failed", str(exc)),
        )

    def _unmount_disk(self, disk: backend.Disk) -> None:
        if self.udisks is None:
            self._error("UDisks2 unavailable", self.udisks_error or "no system bus connection")
            return
        for pool in self.pools:
            for branch in pool.branches:
                if disk.mountpoints and os.path.realpath(branch.path) == os.path.realpath(
                    disk.mountpoints[0]
                ):
                    self._error(
                        "Disk is used by a pool",
                        f"{branch.path} is a branch of {pool.mountpoint}. "
                        "Remove it from the pool first.",
                    )
                    return
        self._set_status(f"Unmounting {disk.device}…")

        def done(_result):
            self._set_status(f"Unmounted {disk.device}")
            self.refresh()

        run_async(
            lambda: self.udisks.unmount(disk.object_path),
            done,
            lambda exc: self._error("Unmount failed", str(exc)),
        )

    def _add_disk_to_pool(self, payload: dict, pool: backend.Pool) -> None:
        mountpoints = [point for point in payload.get("mountpoints") or [] if point]
        if mountpoints:
            self._add_branch(pool, mountpoints[0])
            return

        disk = next((item for item in self.disks if item.device == payload.get("device")), None)
        if disk is None:
            self._error("Disk not found", "The disk disappeared before it could be added.")
            return
        if self.udisks is None:
            self._error("UDisks2 unavailable", "Cannot mount the disk automatically.")
            return

        self._set_status(f"Mounting {disk.device}…")

        def mounted(mountpoint):
            self._set_status(f"Mounted {disk.device} at {mountpoint}")
            self._add_branch(pool, str(mountpoint))

        run_async(
            lambda: self.udisks.mount(disk.object_path),
            mounted,
            lambda exc: self._error("Mount failed", str(exc)),
        )

    def _add_branch(self, pool: backend.Pool, path: str) -> None:
        def work():
            existing = backend.read_branches(pool.mountpoint)
            problem = backend.validate_branch(pool.mountpoint, path, existing)
            if problem:
                raise backend.MergerfsError(problem)
            return backend.add_branch(pool.mountpoint, path)

        def done(branches):
            persisted = self.config.update_branches(
                pool.mountpoint, [branch.path for branch in branches]
            )
            message = f"Added {path} to {pool.mountpoint}"
            if not persisted:
                message += " (external pool: change will not survive a remount)"
            self._set_status(message)
            self.refresh()

        run_async(work, done, lambda exc: self._error("Cannot add branch", str(exc)))

    def _confirm_remove_branch(self, pool_mountpoint: str, path: str) -> None:
        if not pool_mountpoint or not path:
            return
        detail = (
            f"{path}\n\n"
            "Files stay on the disk but disappear from the pool, and open files may fail."
        )
        pool = next((item for item in self.pools if item.mountpoint == pool_mountpoint), None)
        if pool is not None and len(pool.branches) <= 1:
            detail += "\n\nThis is the last branch: the pool will serve no files until another is added."

        def accept():
            def done(branches):
                if branches:
                    self.config.update_branches(
                        pool_mountpoint, [branch.path for branch in branches]
                    )
                self._set_status(f"Removed {path}")
                self.refresh()

            run_async(
                lambda: backend.remove_branch(pool_mountpoint, path),
                done,
                lambda exc: self._error("Cannot remove branch", str(exc)),
            )

        self._confirm("Remove branch?", detail, "Remove", accept)

    def _confirm_unmount_pool(self, mountpoint: str) -> None:
        if not mountpoint:
            return

        def accept():
            def done(_result):
                self._set_status(f"Unmounted {mountpoint}")
                self.refresh()

            run_async(
                lambda: backend.unmount_pool(mountpoint),
                done,
                lambda exc: self._error("Cannot unmount", str(exc)),
            )

        self._confirm(
            "Unmount pool?",
            f"{mountpoint}\n\nOpen files will fail. A busy pool may refuse to unmount.",
            "Unmount",
            accept,
        )

    def _mount_for_new_pool(self, payload: dict) -> None:
        disk = next((item for item in self.disks if item.device == payload.get("device")), None)
        if disk is None:
            self._error("Disk not found", "The disk disappeared before it could be used.")
            return
        if self.udisks is None:
            self._error("UDisks2 unavailable", "Cannot mount the disk automatically.")
            return

        self._set_status(f"Mounting {disk.device}…")

        def done(mountpoint):
            self._set_status(f"Mounted {disk.device} at {mountpoint}")
            self._new_pool_dialog(preset_branch=str(mountpoint))

        run_async(
            lambda: self.udisks.mount(disk.object_path),
            done,
            lambda exc: self._error("Mount failed", str(exc)),
        )

    def _new_pool_dialog(self, preset_branch: str | None = None) -> None:
        entries: list[tuple[str, str]] = [
            (f"{disk.display_name}  ({disk.mountpoints[0]})", disk.mountpoints[0])
            for disk in self.disks
            if disk.mountpoints
        ]
        if preset_branch and all(path != preset_branch for _, path in entries):
            label = f"{os.path.basename(preset_branch) or preset_branch}  ({preset_branch})"
            entries.insert(0, (label, preset_branch))
        if not entries:
            self._error(
                "No mounted disks",
                "Mount a filesystem first, or drag an unmounted disk onto the pool panel.",
            )
            return

        dialog = Gtk.Dialog(title="New pool", transient_for=self, modal=True)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        create_button = dialog.add_button("Create pool", Gtk.ResponseType.OK)
        create_button.add_css_class("suggested-action")

        content = dialog.get_content_area()
        content.set_spacing(10)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_margin_start(16)
        content.set_margin_end(16)

        name_entry = Gtk.Entry(placeholder_text="media")
        dropdown = Gtk.DropDown.new_from_strings([label for label, _ in entries])
        selected = next(
            (index for index, (_, path) in enumerate(entries) if path == preset_branch), 0
        )
        dropdown.set_selected(selected)

        name_label = Gtk.Label(label="Pool name", xalign=0)
        branch_label = Gtk.Label(label="First branch", xalign=0)
        content.append(name_label)
        content.append(name_entry)
        content.append(branch_label)
        content.append(dropdown)

        def on_response(dlg, response):
            if response != Gtk.ResponseType.OK:
                dlg.close()
                return
            name = name_entry.get_text().strip() or "pool"
            index = dropdown.get_selected()
            branch = entries[index][1] if 0 <= index < len(entries) else entries[0][1]
            dlg.close()
            self._create_pool(name, branch)

        dialog.connect("response", on_response)
        dialog.present()

    def _create_pool(self, name: str, branch: str) -> None:
        options = self.config.default_options
        try:
            target = backend.ensure_mountpoint(self.config.pool_base, name)
        except OSError as exc:
            self._error("Cannot create mountpoint", str(exc))
            return

        self._set_status(f"Creating {target}…")

        def work():
            backend.mount_pool([branch], target, options)
            return target

        def done(mountpoint):
            self.config.record_pool(str(mountpoint), name, [branch], options)
            self._set_status(f"Created {mountpoint} with branch {branch}")
            self.refresh()

        run_async(work, done, lambda exc: self._error("Cannot create pool", str(exc)))

    def _autostart_pools(self) -> None:
        entries = self.config.autostart_entries()
        if not entries:
            return

        def work():
            outcome = []
            for entry in entries:
                mountpoint = entry["mountpoint"]
                if backend.is_mounted(mountpoint):
                    continue
                try:
                    os.makedirs(mountpoint, exist_ok=True)
                    backend.mount_pool(
                        entry["branches"], mountpoint, entry.get("options", "")
                    )
                    outcome.append((mountpoint, None))
                except Exception as exc:  # noqa: BLE001
                    outcome.append((mountpoint, str(exc)))
            return outcome

        def done(outcome):
            problems = [f"{path}: {error}" for path, error in outcome if error]
            if problems:
                self._set_status("Autostart: " + "; ".join(problems))
            elif outcome:
                self._set_status("Restored " + ", ".join(path for path, _ in outcome))
            self.refresh()

        run_async(work, done, lambda exc: self._set_status(f"Autostart failed: {exc}"))


class MergerfsApp(Gtk.Application):
    def __init__(self, self_test: bool = False) -> None:
        flags = (
            Gio.ApplicationFlags.NON_UNIQUE
            if self_test
            else Gio.ApplicationFlags.DEFAULT_FLAGS
        )
        super().__init__(application_id=APP_ID, flags=flags)
        self.self_test = self_test

    def do_activate(self) -> None:
        window = MainWindow(self, Config(), self_test=self.self_test)
        window.present()
        if self.self_test:
            GLib.timeout_add(900, self._finish_self_test)

    def _finish_self_test(self) -> bool:
        print("self-test: window constructed and refreshed")
        self.quit()
        return False
