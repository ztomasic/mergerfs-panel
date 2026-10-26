# Architecture

## Shape

```
                 +---------------------------+
                 |        GTK4 window        |
                 |  disks panel | pools panel |
                 +-------------+-------------+
                       |             |
                UDisks2 D-Bus    mountinfo + xattrs
                       |             |
                 +-----v-------------v------+
                 |        backend.py        |
                 | discovery, validation,   |
                 | branch edits, lifecycle  |
                 +--------------------------+
```

`app/src/mergerfs_panel` has four modules:

| Module | Responsibility |
|---|---|
| `__main__.py` | Argument parsing, `Gtk.Application` startup, `--version`, `--self-test` |
| `ui.py` | Window, panels, rows, drag and drop, confirmation dialogs |
| `backend.py` | UDisks2 client, mountinfo parsing, branch xattr protocol, pool mount/unmount |
| `config.py` | JSON persistence under `$XDG_CONFIG_HOME/mergerfs-panel/` |

`backend.py` imports GTK only inside the `UDisks` class, so the core can be tested
headlessly (and in CI containers without a display).

## Discovery

### Disks

The app calls `org.freedesktop.DBus.ObjectManager.GetManagedObjects` on the UDisks2
system-bus object `/org/freedesktop/UDisks2` and keeps every object with an
`org.freedesktop.UDisks2.Filesystem` interface. From the `Block` interface it reads
the device node, label, filesystem type, size, and hints; from the `Drive` interface
it reads removable state and model.

D-Bus `ay` arrays (the device node and mount points) arrive through PyGObject as
lists of ints in some versions, so they are decoded by hand. Mount and unmount call
`Filesystem.Mount` / `Filesystem.Unmount` with an empty option dictionary and a
120-second timeout, which leaves time for the polkit prompt. The calls run on a
worker thread so the UI stays responsive while the dialog is open.

UDisks2 is the only component that needs authorization. It cannot mount
`fuse.mergerfs` — its supported filesystem list does not contain any `fuse.*` type —
which is why the app mounts pools itself.

### Pools

Pools are found by parsing `/proc/self/mountinfo` and selecting entries whose
filesystem type is `fuse.mergerfs`. Mountinfo fields are octal-escaped (`\040` for a
space, and so on) and are unescaped before use.

The mount source is not a reliable branch list: when the pool was mounted with
`fsname=`, the source is that name. The authoritative list is the
`user.mergerfs.branches` xattr on the pseudo-file `<mountpoint>/.mergerfs`, which
mergerfs exposes for reading and writing. It is read on every refresh; pools whose
xattr cannot be read (for example, a pool mounted by root) show an unavailable branch
list.

## Branch protocol

mergerfs parses the xattr value as an instruction:

| Value written | Effect |
|---|---|
| `+</path` | Prepend a branch (what the app uses for drops) |
| `+>/path` or `+/path` | Append a branch |
| `-/path` | Remove branches whose path matches the pattern (`fnmatch`; `*` and `?` work) |
| `-<` | Remove the first branch |
| `->` | Remove the last branch |
| `/a:/b:/c` | Replace the whole list |
| `[list]` | **Not supported** — the upstream documentation's bracket notation is rejected with `EINVAL` |

Branch designations carry options after `=`: `/mnt/disk1=RO` excludes a branch from
create policies, `=NC` excludes it from creates but allows changes, and a numeric
value sets a per-branch `minfreespace`. Reads return the normalized form
(`/path=RW`).

The app's removal path first tries the exact-match form (`-/path`) and then verifies
the result. Paths containing glob metacharacters, and any unexpected no-op, fall back
to writing the full remaining list. Every mutation is verified by reading the xattr
back, because invalid values can be accepted silently (the `-[...]` case above).

### Validation

Before a write, the caller runs `validate_branch`:

- the path must resolve and be a directory;
- it must not equal the pool mount point;
- it must not contain the pool mount point (recursion through the parent);
- it must not live inside the pool (recursion through the child);
- it must not duplicate an existing branch after `realpath`.

## Pool lifecycle

`mount_pool` runs `mergerfs [-o options] branch1:branch2:<...> mountpoint`, waits up to
60 seconds, and verifies the result through mountinfo. mergerfs prints a warning when
not running as root; it is harmless for user-owned branches.

`unmount_pool` tries helpers in order: `fusermount3 -u` (works for user-owned FUSE
mounts), `mergerfs-fusermount -u`, then `umount`. The first one that returns success
*and* makes the mount disappear wins; otherwise the last error is reported. Lazy
unmount is available in the backend but is never used automatically.

New pools are created under `pool_base`, which defaults to `~/mergerfs`. The directory
is user-owned so that the unprivileged FUSE mount is allowed to mount over it.

## Persistence

The config file stores the desired state because mergerfs runtime changes are not
persisted by the filesystem itself:

```json
{
  "version": 1,
  "pool_base": "~/mergerfs",
  "default_options": "category.create=mfs,minfreespace=4G",
  "pools": { "<mountpoint>": { "name": "...", "branches": ["..."], "options": "...", "autostart": true } }
}
```

Writes go to a temporary file and are renamed into place. On startup, entries with
`autostart` whose mount point is free and that have at least one existing branch are
mounted from a single worker thread. Failures are reported in the status bar and do
not abort startup.

External pools (not in the config) can be edited live, but nothing is persisted for
them; the UI warns about this.

## Threading and UI updates

Blocking work — UDisks2 calls, subprocess mounts, xattr writes — runs on short-lived
worker threads. Results return through `GLib.idle_add`, which is the only place the
UI is touched. Refresh is serialized by a flag so a slow refresh cannot overlap the
next one. There are no timers: refresh happens at startup, after each action, and on
the Refresh button.

## Drag and drop

Each drag source provides a JSON payload as a string through
`Gdk.ContentProvider.new_for_value`:

```json
{"kind": "disk", "device": "/dev/sdb2", "mountpoints": ["/run/media/you/SHARE"]}
{"kind": "branch", "pool": "/home/you/mergerfs/media", "path": "/run/media/you/SHARE"}
{"kind": "pool", "mountpoint": "/home/you/mergerfs/media"}
```

Drop targets accept strings and dispatch on `kind`. The pools panel has one target
for the empty area (create a pool) and one per pool card (add a branch); the disks
panel accepts branches (remove) and pools (unmount). Dropping an unmounted disk
mounts it through UDisks2 first and then adds the resulting mount point.

## Why a pool is not a device

Dolphin and other KIO-based file managers build their device list from
`KFilePlacesModel`, whose Solid predicate accepts volumes with
`StorageVolume.usage == FileSystem` (or `Encrypted`) and accessible storage. Solid
gets those records from UDisks2 block devices. A mergerfs pool is a FUSE mount with
no block device, so Solid has no record for it and no device entry can be created.
This was verified on a live system: `solid-hardware6 list` contains the physical
disks as `StorageVolume`/`StorageAccess` and no entry for the pool.

The pool is therefore accessed as a directory and can be bookmarked, but it will
never have a mount/eject action in a file manager's device pane. Mount and unmount
belong to the app (or to a custom file-manager action).

## Capacity semantics

mergerfs reports aggregated `statfs` data for the pool. On a live test with an 8 GB
and a 21 GB branch, the union reported 29 GB total and 21 GB available. This is an
aggregate for planning writes, not a single filesystem: files are never split, and
`minfreespace` prevents a branch from being filled to the last byte.

## Security model

- No setuid binary, no long-running root helper, no custom polkit policy.
- Authorization for block-device operations is delegated to UDisks2/polkit.
- Pools run with the privileges of the user who created them.
- Xattr writes are restricted by the kernel to the mount owner, so the app's blast
  radius is the user's own mounts.
- Paths are resolved before validation, which prevents a symlink from turning a
  branch into the pool itself or its parent.

## Known constraints

- **GTK 4.10+** is required for `Gtk.AlertDialog`; older toolkits can build the app
  but dialogs fail.
- On Wayland, GTK lays out in the frame clock. A window that is fully occluded (for
  example behind a lock screen) stops receiving frame callbacks, so newly added rows
  are not laid out until it is visible again. This is normal GTK behaviour, not data
  loss; the widget tree is updated.
- Pools mounted by another user or by root are not editable by this process.

## Non-goals

- Splitting files across branches, RAID, parity, or snapshots.
- Managing fstab or systemd units.
- Browsing or copying files.
- A daemon, tray icon, or remote API.
