# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-10-26

### Added

- **Mount pools at boot.** A checkbox in the header bar installs and enables a
  systemd user service and turns on lingering, so managed pools are restored at
  boot without starting the application.
- **`--restore-pools`** headless mode (with `--wait SECONDS`) that mounts the
  configured pools, waits for branch directories to appear — for example disks
  mounted at login — and logs the outcome. The boot service runs this command.
- Boot restore honours each pool's `autostart` flag. Pools with no branch
  directory are skipped with a log message; after the deadline, remaining pools
  are mounted with the branches that exist.
- 13 new tests: unit generation and systemd quoting, service install and rollback
  with mocked systemd, and live restore tests (full branches, missing branch,
  late branch, already mounted, autostart disabled, no pools).

### Changed

- The generated unit pins `PYTHONPATH` to the package that created it, so the
  service never silently runs a different installed version.

### Notes

- Branch filesystems must be mounted before mergerfs can use them. The app does
  not mount disks at boot; it waits for them for up to ten minutes.
- Toggling the checkbox requires one authorization prompt to enable lingering.
  Disabling it removes the unit but leaves lingering enabled, since other user
  services may rely on it.

## [0.1.0] - 2026-10-26

First public release.

### Added

- Two-panel GTK4 window: filesystems on the left, mounted mergerfs pools on the right.
- Disk rows with label, filesystem type, size, mount point, and system/removable
  markers; mount and unmount through UDisks2 with polkit authentication.
- Pool cards showing branch count, aggregate capacity, per-branch free space, branch
  flags, and an unmount action.
- Drag-and-drop branch management on live mounts: disk onto pool to add, branch onto
  the disks panel to remove, pool onto the disks panel to unmount.
- Live branch edits through mergerfs' `user.mergerfs.branches` xattr interface
  (`+<path`, `+>path`, `-path`, full replacement), verified by reading the list back.
- New-pool dialog, including creating a pool by dropping a disk on the empty panel.
- Persistence of created pools and their branches in
  `~/.config/mergerfs-panel/config.json`, with optional autostart at app launch.
- Safety rules: no recursive branches, no duplicates, no unmounting disks used by a
  pool, confirmation before removing the last branch.
- Packaging: Fedora RPM spec, Debian packaging, Arch PKGBUILD, and a universal
  `install.sh`/`uninstall.sh` with `PREFIX`/`DESTDIR` support.
- Desktop entry, SVG icon, and AppStream metadata.
- Test suite: 22 tests including a live mergerfs integration test and UDisks2
  enumeration.

### Known limitations

- Requires GTK 4.10 or newer.
- Pools mounted by root or another user are listed read-only for branch edits.
- Pools are restored when the app starts, not at boot; use fstab/systemd for boot
  mounts.
- Branch changes on pools not managed by the app are live only.
- A mergerfs pool is a FUSE mount and cannot appear in a file manager's device pane.

[0.2.0]: https://github.com/ztomasic/mergerfs-panel/releases/tag/v0.2.0
[0.1.0]: https://github.com/ztomasic/mergerfs-panel/releases/tag/v0.1.0
