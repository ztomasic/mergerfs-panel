# Usage

## The window

![MergerFS Panel](screenshot.png)

**Left panel — Disks.** One row per filesystem UDisks2 reports: device name, label,
filesystem type, size, mount point, and whether it is a system or removable volume.
The button on the right mounts or unmounts the filesystem through UDisks2. Rows are
drag sources.

**Right panel — mergerfs pools.** One card per mounted pool. The header shows the
mount point, branch count, capacity, and whether the pool is managed by this app.
The eject button unmounts the pool. Each branch row shows its path, free space, and
any branch flags, with a remove button. Cards and branch rows are drag sources.

**Header.** Refresh re-reads disks, mounts, and branch lists. New pool opens the
creation dialog.

**Status bar.** Shows the result of the last action, including warnings about
external pools and autostart failures.

## Gestures

| Drag | Drop on | Result |
|---|---|---|
| Disk | A pool card | Mount the disk if needed, then add it as a branch (`+<path`) |
| Disk | Empty pools area | Open *New pool* with that disk preselected as the first branch |
| Branch | Disks panel | Remove the branch (`-path`); files stay on the disk |
| Pool header | Disks panel | Unmount the pool |

Every action asks for confirmation before changing or unmounting anything, except
adding a branch (which is non-destructive).

## Pools

### Creating a pool

Use **New pool** in the header, or drop a disk onto the empty pools column. Choose a
name and the first branch. The pool is mounted at `<pool_base>/<name>`, where
`pool_base` defaults to `~/mergerfs`. The directory is created for you.

The default mount options are `category.create=mfs,minfreespace=4G`:

- `category.create=mfs` writes each new file to the branch with the most free space.
  Use `epmfs` if your data is organised in folders and you want a folder's files to
  stay on one disk.
- `minfreespace=4G` keeps that much space free on each branch before it is considered
  full.

Change `default_options` in the config file to use different options for new pools.

### Adding and removing branches

Adding a branch is immediate: the app writes `+<path` to the
`user.mergerfs.branches` xattr of the live mount. mergerfs inserts the new branch
into its list and new writes can use it immediately. Nothing is unmounted and open
files keep working.

Removing a branch is also immediate. The files on that disk remain intact; they
simply disappear from the merged directory. Removing the last branch asks for an
extra confirmation because the pool will serve no files until another is added.

### Capacity is aggregated, files are not

The pool reports the sum of its branches' capacity. With an 8 GB disk and a 21 GB
disk, `df` on the pool shows about 29 GB, and new files are placed according to the
create policy. This is *not* a single filesystem: each file lives entirely on one
branch, so a single file larger than the largest branch's free space cannot be
created. For block-level spanning, use LVM, btrfs multi-device, ZFS, or mdadm — see
the [FAQ](FAQ.md).

### Finding which branch holds a file

mergerfs exposes per-file xattrs:

```bash
getfattr -n user.mergerfs.basepath --only-values /path/inside/pool/file
# /run/media/you/disk1

getfattr -n user.mergerfs.allpaths --only-values /path/inside/pool/file | tr '\0' '\n'
```

`basepath` is the branch the file was resolved through; `allpaths` lists every
branch containing a file with that relative path.

### Unmounting

Unmounting tries `fusermount3 -u`, then `mergerfs-fusermount -u`, then `umount`.
A busy pool returns the helper's error. Close open files, stop services using the
pool, then retry. The app never performs a lazy unmount automatically.

## Restore pools at boot

The **Mount pools at boot** checkbox in the header installs a systemd user service
at `~/.config/systemd/user/mergerfs-panel-restore.service` and enables it. So that
the service can start before you log in, the app also enables lingering for your
user (`loginctl enable-linger`), which asks for authorization once.

The unit runs:

```
<python> -m mergerfs_panel --restore-pools --wait 600
```

At boot it mounts every managed pool whose `autostart` is true and exits. Pools that
are already mounted are skipped. The application does not need to run and no window
is created; output goes to the systemd journal.

### Branch availability

mergerfs can only pool mounted filesystems. At boot, removable disks may not be
mounted yet, so the restore command polls for the configured branch directories:

- a pool is mounted as soon as all of its branches exist;
- when the deadline passes (10 minutes in the generated unit), remaining pools are
  mounted with the branches that exist, and the missing ones are logged;
- pools with no branch directory at all are skipped.

If your disks are mounted by the desktop at login, log in within the wait window for
boot restore to succeed. Disks that must always be available at boot belong in
fstab or a systemd mount unit, not in desktop removable-media handling.

### Running it manually

```bash
mergerfs-panel --restore-pools --wait 0     # try now, do not wait
mergerfs-panel --restore-pools --wait 120   # wait up to two minutes
```

### Status and turning it off

```bash
systemctl --user status mergerfs-panel-restore.service
journalctl --user -u mergerfs-panel-restore.service -b
```

Unchecking the box disables and removes the unit. Lingering is left enabled: it is a
per-user setting that other user services may rely on, and on its own it starts
nothing.

## File managers

A mergerfs pool is a FUSE mount with no block device, so it does not appear in a
file manager's Devices list (Dolphin, GNOME Files, Thunar, and others build that
list from block-device information). This is expected. Bookmark the pool's mount
point in your file manager to give it a permanent entry in the sidebar.

The physical disks remain ordinary mounted devices and continue to appear in the
Devices list. That is also expected: mergerfs does not hide its branches.

## Configuration

`~/.config/mergerfs-panel/config.json`:

```json
{
  "version": 1,
  "pool_base": "/home/you/mergerfs",
  "default_options": "category.create=mfs,minfreespace=4G",
  "pools": {
    "/home/you/mergerfs/media": {
      "name": "media",
      "branches": ["/run/media/you/disk1", "/run/media/you/disk2"],
      "options": "category.create=mfs,minfreespace=4G",
      "autostart": true
    }
  }
}
```

- `pool_base` — parent directory for pools created by the app.
- `default_options` — mount options for new pools.
- `pools` — keyed by mount point. Entries are written when a pool is created and
  when its branches change.
- `autostart` — if true, the app mounts the pool at startup when at least one branch
  directory exists. Missing branches are skipped.

The value of `XDG_CONFIG_HOME` is honoured, so the path may differ if you changed it.
The file is written atomically (temporary file plus rename).

## Managed and external pools

A pool is **managed** if it has an entry in the config file. Branch changes on
managed pools are written back to the config, so they survive a remount. A pool
mounted outside the app is **external**: the app can still show it and change its
branches live, but the status bar warns that the change will not survive a remount.

Managing an external pool permanently means mounting it from fstab or a systemd unit
with the desired branch list; the app is not a configuration store for those.

## Privileges

- Disks are mounted through UDisks2, which asks polkit for authorization when needed.
- Pools are mounted by the app's user; FUSE requires no root.
- Branch xattr writes are allowed only for the user who owns the mount. A pool
  mounted by root or by another user is listed but not editable (the branch list may
  also be unreadable); run the app as the mount owner to manage it.

## Safety rules

- A branch must be an existing directory.
- It cannot be the pool mount point, contain it, or live inside it.
- It cannot duplicate an existing branch (paths are compared after `realpath`).
- Unmounting a disk that is currently a branch of a mounted pool is refused.
- Removing a branch never deletes files.

## Debugging

Set `MFP_DEBUG=1` to log refreshes, results, and errors to stderr:

```bash
MFP_DEBUG=1 mergerfs-panel
```

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for common problems.
