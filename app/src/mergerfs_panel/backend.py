"""Core logic: mount tables, mergerfs runtime control and UDisks2 access.

Nothing here imports GTK at module level, so the file is testable headlessly.
The UDisks2 client talks to the system bus directly; it never needs root,
because udisks2 performs authentication through polkit.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field

MERGERFS_FSTYPE = "fuse.mergerfs"
BRANCH_XATTR = "user.mergerfs.branches"
RUNTIME_FILE = ".mergerfs"

_UNESCAPE_RE = re.compile(r"\\([0-7]{3})")
_UNSAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class MergerfsError(RuntimeError):
    """A mergerfs operation failed; the message is user-facing."""


class UDisksError(RuntimeError):
    """An operation through UDisks2 failed; the message is user-facing."""


# --------------------------------------------------------------------------
# Mount table
# --------------------------------------------------------------------------


def _unescape(value: str) -> str:
    """Undo the octal escaping mountinfo applies to spaces and friends."""
    return _UNESCAPE_RE.sub(lambda m: chr(int(m.group(1), 8)), value)


def parse_mountinfo(text: str) -> list[dict]:
    """Parse /proc/self/mountinfo into dictionaries."""
    mounts: list[dict] = []
    for line in text.splitlines():
        if " - " not in line:
            continue
        left, right = line.split(" - ", 1)
        lfields = left.split()
        rfields = right.split()
        if len(lfields) < 6 or len(rfields) < 3:
            continue
        mounts.append(
            {
                "id": lfields[0],
                "parent": lfields[1],
                "dev": lfields[2],
                "root": _unescape(lfields[3]),
                "mountpoint": _unescape(lfields[4]),
                "options": lfields[5].split(","),
                "fstype": rfields[0],
                "source": _unescape(rfields[1]),
                "super_options": rfields[2].split(","),
            }
        )
    return mounts


def read_mountinfo() -> list[dict]:
    try:
        with open("/proc/self/mountinfo", encoding="utf-8", errors="surrogateescape") as fh:
            return parse_mountinfo(fh.read())
    except OSError:
        return []


def _canonical(path: str) -> str:
    resolved = os.path.realpath(path).rstrip(os.sep)
    return resolved or os.sep


def is_mounted(path: str) -> bool:
    target = _canonical(path)
    return any(_canonical(m["mountpoint"]) == target for m in read_mountinfo())


# --------------------------------------------------------------------------
# Branches
# --------------------------------------------------------------------------


@dataclass
class Branch:
    path: str
    flags: str = "RW"

    @property
    def writable(self) -> bool:
        return "RO" not in {flag.strip() for flag in self.flags.split(",")}

    def designation(self) -> str:
        flags = self.flags.strip()
        if not flags or flags == "RW":
            return self.path
        return f"{self.path}={flags}"


@dataclass
class Pool:
    mountpoint: str
    source: str
    branches: list[Branch] = field(default_factory=list)

    @property
    def name(self) -> str:
        return os.path.basename(self.mountpoint.rstrip(os.sep)) or self.mountpoint


@dataclass
class Disk:
    device: str
    label: str = ""
    fs_type: str = ""
    size: int = 0
    mountpoints: list[str] = field(default_factory=list)
    object_path: str = ""
    system: bool = False
    removable: bool = False
    model: str = ""

    @property
    def mounted(self) -> bool:
        return bool(self.mountpoints)

    @property
    def short_name(self) -> str:
        return os.path.basename(self.device) or self.device

    @property
    def display_name(self) -> str:
        if self.label:
            return f"{self.short_name} — {self.label}"
        return self.short_name


def parse_branches(spec: str) -> list[Branch]:
    """Turn ``/a=RW:/b=RO`` into Branch objects."""
    branches: list[Branch] = []
    if not spec:
        return branches
    for item in spec.split(":"):
        item = item.strip()
        if not item:
            continue
        path, sep, flags = item.partition("=")
        branches.append(Branch(path=path, flags=flags if sep else "RW"))
    return branches


def branches_to_spec(branches: list[Branch]) -> str:
    return ":".join(branch.designation() for branch in branches)


def runtime_path(mountpoint: str) -> str:
    return os.path.join(mountpoint, RUNTIME_FILE)


def read_branches(mountpoint: str) -> list[Branch]:
    """Read the live branch list through mergerfs' xattr interface."""
    try:
        raw = os.getxattr(runtime_path(mountpoint), BRANCH_XATTR)
    except OSError:
        return []
    return parse_branches(raw.decode("utf-8", "surrogateescape"))


def write_branch_spec(mountpoint: str, spec: str) -> None:
    try:
        os.setxattr(runtime_path(mountpoint), BRANCH_XATTR, spec.encode("utf-8", "surrogateescape"))
    except OSError as exc:
        raise MergerfsError(f"cannot change branches: {exc.strerror or exc}") from exc


def add_branch(mountpoint: str, path: str, flags: str = "RW", prepend: bool = True) -> list[Branch]:
    """Add a branch to a live pool.

    mergerfs accepts ``+<path`` (prepend) and ``+>path`` (append); both are
    handled inside the filesystem, so nothing is unmounted.
    """
    prefix = "+<" if prepend else "+>"
    designation = Branch(path=path, flags=flags).designation()
    write_branch_spec(mountpoint, prefix + designation)
    return read_branches(mountpoint)


def remove_branch(mountpoint: str, path: str) -> list[Branch]:
    """Remove a branch from a live pool, preferring the exact-match form."""
    current = read_branches(mountpoint)
    wanted = _canonical(path)
    remaining = [branch for branch in current if _canonical(branch.path) != wanted]
    if len(remaining) == len(current):
        return current

    if not any(char in path for char in "*?["):
        try:
            write_branch_spec(mountpoint, "-" + path)
            after = read_branches(mountpoint)
            if len(after) == len(remaining) and all(
                _canonical(branch.path) != wanted for branch in after
            ):
                return after
        except MergerfsError:
            pass

    # Globs (or an unexpected no-op) fall back to writing the full list.
    write_branch_spec(mountpoint, branches_to_spec(remaining))
    return read_branches(mountpoint)


def replace_branches(mountpoint: str, branches: list[Branch]) -> list[Branch]:
    if not branches:
        raise MergerfsError("a pool needs at least one branch")
    write_branch_spec(mountpoint, branches_to_spec(branches))
    return read_branches(mountpoint)


def validate_branch(mountpoint: str, path: str, existing: list[Branch] = ()) -> str | None:
    """Return an error message when *path* must not become a branch."""
    if not path:
        return "no path given"
    try:
        pool = _canonical(mountpoint)
        candidate = _canonical(path)
    except OSError as exc:
        return f"cannot resolve path: {exc}"

    if not os.path.isdir(candidate):
        return f"{path} is not a directory"
    if candidate == pool:
        return "the pool mountpoint cannot be its own branch"
    if pool.startswith(candidate.rstrip(os.sep) + os.sep):
        return f"{path} contains the pool mountpoint (would recurse)"
    if candidate.startswith(pool.rstrip(os.sep) + os.sep):
        return f"{path} is inside the pool (would recurse)"
    for branch in existing:
        if _canonical(branch.path) == candidate:
            return f"{path} is already a branch"
    return None


def usage(path: str) -> tuple[int, int]:
    """Return (total, free) bytes for *path*; (0, 0) when unavailable."""
    try:
        stats = os.statvfs(path)
    except OSError:
        return (0, 0)
    return (stats.f_blocks * stats.f_frsize, stats.f_bavail * stats.f_frsize)


def list_pools() -> list[Pool]:
    pools = []
    for mount in read_mountinfo():
        if mount["fstype"] != MERGERFS_FSTYPE:
            continue
        mountpoint = mount["mountpoint"]
        pools.append(
            Pool(
                mountpoint=mountpoint,
                source=mount["source"],
                branches=read_branches(mountpoint),
            )
        )
    return sorted(pools, key=lambda pool: pool.mountpoint)


# --------------------------------------------------------------------------
# Pool lifecycle
# --------------------------------------------------------------------------


def mergerfs_available() -> bool:
    return shutil.which("mergerfs") is not None


def ensure_mountpoint(base: str | os.PathLike[str], name: str) -> str:
    """Create (and return) a mountpoint directory under *base*."""
    safe = _UNSAFE_NAME_RE.sub("-", name).strip("-") or "pool"
    target = os.path.join(os.path.expanduser(str(base)), safe)
    os.makedirs(target, exist_ok=True)
    return target


def mount_pool(branches: list[str], mountpoint: str, options: str = "") -> None:
    if not mergerfs_available():
        raise MergerfsError("mergerfs is not installed")
    if not branches:
        raise MergerfsError("a pool needs at least one branch")
    if is_mounted(mountpoint):
        raise MergerfsError(f"{mountpoint} is already a mountpoint")

    argv = ["mergerfs"]
    opts = [opt.strip() for opt in (options or "").split(",") if opt.strip()]
    if opts:
        argv += ["-o", ",".join(opts)]
    argv += [":".join(branches), mountpoint]

    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    except FileNotFoundError as exc:
        raise MergerfsError("mergerfs is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise MergerfsError("mergerfs did not finish mounting in time") from exc

    if result.returncode != 0:
        message = result.stderr.strip() or f"mergerfs exited with status {result.returncode}"
        raise MergerfsError(message)
    if not is_mounted(mountpoint):
        raise MergerfsError(
            "mergerfs exited without mounting; check that the mountpoint is writable"
        )


def unmount_pool(mountpoint: str, allow_lazy: bool = False) -> None:
    if not is_mounted(mountpoint):
        return

    attempts: list[list[str]] = [
        ["fusermount3", "-u", mountpoint],
        ["mergerfs-fusermount", "-u", mountpoint],
        ["umount", mountpoint],
    ]
    if allow_lazy:
        attempts.append(["umount", "-l", mountpoint])

    errors: list[str] = []
    for argv in attempts:
        executable = shutil.which(argv[0])
        if executable is None:
            continue
        try:
            result = subprocess.run([executable, *argv[1:]], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f"{argv[0]}: {exc}")
            continue
        if result.returncode == 0 and not is_mounted(mountpoint):
            return
        errors.append(f"{argv[0]}: {result.stderr.strip() or f'status {result.returncode}'}")

    detail = errors[-1] if errors else "no unmount helper available"
    raise MergerfsError(f"could not unmount {mountpoint}: {detail}")


# --------------------------------------------------------------------------
# UDisks2
# --------------------------------------------------------------------------


def _strip_dbus_error(message: str) -> str:
    for prefix in ("GDBus.Error:", "org.freedesktop.UDisks2.Error."):
        if message.startswith(prefix):
            message = message[len(prefix) :]
    return message.strip() or "unknown error"


class UDisks:
    """Minimal UDisks2 client: enumerate filesystems, mount and unmount them."""

    BUS_NAME = "org.freedesktop.UDisks2"
    OBJECT_PATH = "/org/freedesktop/UDisks2"

    def __init__(self) -> None:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio

        self._Gio = Gio
        self._bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        self._manager = Gio.DBusProxy.new_sync(
            self._bus,
            Gio.DBusProxyFlags.NONE,
            None,
            self.BUS_NAME,
            self.OBJECT_PATH,
            "org.freedesktop.DBus.ObjectManager",
            None,
        )

    @staticmethod
    def _as_text(value: object) -> str:
        if isinstance(value, (bytes, bytearray)):
            return value.rstrip(b"\x00").decode("utf-8", "replace")
        if isinstance(value, (list, tuple)) and all(isinstance(item, int) for item in value):
            # D-Bus 'ay' arrays arrive as lists of ints through some bindings.
            return bytes(value).rstrip(b"\x00").decode("utf-8", "replace")
        if value is None:
            return ""
        return str(value)

    def _objects(self) -> dict:
        reply = self._manager.call_sync(
            "GetManagedObjects",
            None,
            self._Gio.DBusCallFlags.NONE,
            15000,
            None,
        )
        return reply.unpack()[0]

    def list_disks(self) -> list[Disk]:
        objects = self._objects()
        disks: list[Disk] = []
        for object_path, interfaces in objects.items():
            filesystem = interfaces.get("org.freedesktop.UDisks2.Filesystem")
            if not filesystem:
                continue
            block = interfaces.get("org.freedesktop.UDisks2.Block", {})
            device = self._as_text(block.get("Device") or block.get("PreferredDevice"))
            if not device:
                continue

            drive: dict = {}
            drive_path = block.get("Drive")
            if drive_path:
                drive = objects.get(drive_path, {}).get("org.freedesktop.UDisks2.Drive", {})

            mountpoints = [
                self._as_text(point)
                for point in (filesystem.get("MountPoints") or [])
                if self._as_text(point)
            ]
            disks.append(
                Disk(
                    device=device,
                    label=self._as_text(block.get("IdLabel")),
                    fs_type=self._as_text(block.get("IdType")) or "unknown",
                    size=int(block.get("Size") or filesystem.get("Size") or 0),
                    mountpoints=mountpoints,
                    object_path=object_path,
                    system=bool(block.get("HintSystem")),
                    removable=bool(drive.get("Removable")),
                    model=self._as_text(drive.get("Model")),
                )
            )
        return sorted(disks, key=lambda disk: disk.device)

    def _filesystem_proxy(self, object_path: str):
        return self._Gio.DBusProxy.new_sync(
            self._bus,
            self._Gio.DBusProxyFlags.NONE,
            None,
            self.BUS_NAME,
            object_path,
            "org.freedesktop.UDisks2.Filesystem",
            None,
        )

    def mount(self, object_path: str) -> str:
        from gi.repository import GLib

        proxy = self._filesystem_proxy(object_path)
        try:
            reply = proxy.call_sync(
                "Mount",
                GLib.Variant("(a{sv})", ({},)),
                self._Gio.DBusCallFlags.NONE,
                120000,
                None,
            )
        except Exception as exc:  # GLib.Error, DBus errors
            raise UDisksError(_strip_dbus_error(str(exc))) from exc
        return str(reply.unpack()[0])

    def unmount(self, object_path: str) -> bool:
        from gi.repository import GLib

        proxy = self._filesystem_proxy(object_path)
        try:
            reply = proxy.call_sync(
                "Unmount",
                GLib.Variant("(a{sv})", ({},)),
                self._Gio.DBusCallFlags.NONE,
                120000,
                None,
            )
        except Exception as exc:
            raise UDisksError(_strip_dbus_error(str(exc))) from exc
        return bool(reply.unpack()[0])
