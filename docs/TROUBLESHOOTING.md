# Troubleshooting

Set `MFP_DEBUG=1` before starting the app to log refresh results and errors to the
terminal:

```bash
MFP_DEBUG=1 mergerfs-panel
```

## The pool is not listed in my file manager's Devices sidebar

Expected. A mergerfs pool is a FUSE mount without a block device, so Solid/UDisks2
never report it as a storage volume and file managers cannot show a device entry.
Bookmark the mount point instead. See [ARCHITECTURE.md](ARCHITECTURE.md#why-a-pool-is-not-a-device).

## My physical disks disappeared from Dolphin

Dolphin builds its device list from Solid at startup and on hotplug. If the disks are
mounted but missing:

1. Press **F9** to show the Places panel and expand **Devices** / **Removable Devices**.
2. Restart Dolphin.
3. Check that Solid sees them:

   ```bash
   solid-hardware6 list details | grep -A12 "block_devices/sdb1"
   ```

   A usable disk has `StorageVolume.usage = 'FileSystem'`, `StorageVolume.ignored = false`,
   and `StorageAccess.accessible = true`.

Restarting Dolphin does not affect the pool; the pool never had a device entry.

## "cannot change branches: Permission denied"

The pool is mounted by root or by a different user. Branch xattrs can only be written
by the mount owner (or root). Check the owner:

```bash
findmnt -T /path/to/pool -o TARGET,SOURCE,FSTYPE,OPTIONS
# user_id=1000 means user 1000 owns the mount
```

Run the app as the user who mounted the pool. To manage a root-mounted pool, either
remount it as yourself or accept that its branch list is read-only here.

## The pool card says "branch list unavailable"

The `user.mergerfs.branches` xattr on `<mountpoint>/.mergerfs` could not be read. This
usually means the mount belongs to another user, or the mount point is not a
mergerfs mount any more. The pool is still listed from `/proc/self/mountinfo`; only
branch editing is unavailable.

```bash
getfattr -n user.mergerfs.branches --only-values /path/to/pool/.mergerfs
findmnt -T /path/to/pool -o FSTYPE
```

## "Cannot mount … is already a mountpoint"

Something else is mounted at the chosen directory. Mount the disk somewhere else or
unmount the existing mount first. The app never mounts over a non-empty mount point.

## "Cannot create pool: mergerfs exited without mounting"

The mount point is not writable by your user, so FUSE refused the mount. Pools
created by the app live under `~/mergerfs`, which is user-owned. If you changed
`pool_base` to a root-owned directory such as `/mnt`, either make the directory
writable or mount pools as root through fstab/systemd.

## "mergerfs is not installed"

mergerfs is not in Fedora's repositories. Install the upstream RPM or `.deb` from
<https://github.com/trapexit/mergerfs/releases>. Listing disks and existing pools
works without it.

## Unmount fails with "Device or resource busy"

A process still has files open on the pool, or its working directory there. Find it:

```bash
lsof +f -- /path/to/pool
fuser -vm /path/to/pool
```

Close the files or stop the service, then retry. The app deliberately does not fall
back to a lazy unmount; `umount -l` hides the mount while data is still in use and
can surprise you later. If you accept that risk, run it yourself.

## "Disk is used by a pool"

The app refuses to unmount a filesystem that is currently a branch. Remove the branch
first (drag it to the disks panel or use the trash button), then unmount the disk.
Removing a branch does not delete its files.

## The window does not update while it is behind other windows

On Wayland, GTK lays out on frame callbacks. A completely occluded window — or one
behind a lock screen — stops receiving them, so rows added during that time are not
laid out until the window becomes visible. Bring the window to the front and it
catches up. No data is lost.

## Autostart did not restore a pool

The status bar reports why. Common causes:

- no branch directory exists (the disk is not mounted yet);
- the mount point is busy;
- the pool was mounted by another user.

Autostart at app launch is separate from the **Mount pools at boot** checkbox; the
next section covers the boot service.

## Pools are not restored at boot

1. Check the checkbox and the two systemd facts behind it:

   ```bash
   systemctl --user is-enabled mergerfs-panel-restore.service
   loginctl show-user "$USER" -p Linger --value
   ```

   The box is checked only when the unit is enabled **and** lingering is on. If
   lingering is off, toggle the box again and approve the authorization prompt.

2. Inspect the service and its journal:

   ```bash
   systemctl --user status mergerfs-panel-restore.service
   journalctl --user -u mergerfs-panel-restore.service -b
   ```

3. Run the restore command manually to see why a pool was skipped:

   ```bash
   mergerfs-panel --restore-pools --wait 0
   ```

4. Verify the pool is in the config with `autostart: true`, and that its branches
   are directories at restore time. The service does not mount disks.

5. If the branch filesystems are mounted by the desktop at login, they may appear
   after the unit's ten-minute deadline. Move them to fstab/systemd or log in
   within the window.

Boot restore requires systemd. On other init systems, use fstab or the init system's
own unit to mount the pool.

## A web server gets 403 or 404 from the pool

Check both:

1. Is the pool mounted? `findmnt -T /path/to/pool -o FSTYPE` must print
   `fuse.mergerfs`. If it is unmounted, the directory underneath is empty.
2. Can the server's user read the mount? A user-mounted FUSE pool is private to that
   user. `allow_other` plus `user_allow_other` in `/etc/fuse.conf` is required for
   other users; the cleanest option for a service is a root-owned boot-time mount at
   `/srv/…`. See [INSTALL.md](INSTALL.md#making-a-pool-available-to-other-users-and-services).

## The app does not start

```bash
python3 -c 'import gi; gi.require_version("Gtk", "4.0"); from gi.repository import Gtk; print(Gtk.get_minor_version())'
```

- `ModuleNotFoundError: gi` — install PyGObject (`python3-gobject`, `python3-gi`,
  `python-gobject`).
- GTK minor version below 10 — the app needs GTK 4.10 or newer for
  `Gtk.AlertDialog`.
- `mergerfs-panel --self-test` builds the window, refreshes once, and exits; it is a
  quick way to check that the GUI stack works without interacting with it.

## Reporting a bug

Include:

```bash
mergerfs-panel --version
cat /etc/os-release | head -2
mergerfs --version
findmnt -t fuse.mergerfs -o TARGET,SOURCE,OPTIONS
MFP_DEBUG=1 mergerfs-panel   # reproduce, then copy the terminal output
```

Open an issue with the template and redact paths you consider private.
