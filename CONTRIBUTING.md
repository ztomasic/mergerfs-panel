# Contributing

Thanks for considering a contribution. This is a small desktop utility; keeping it
focused and dependable matters more than adding surface area.

## Reporting bugs

Open an issue with the bug template and include:

- `mergerfs-panel --version`
- distribution and version (`cat /etc/os-release`)
- desktop environment (KDE/GNOME/other) and whether the session is Wayland or X11
- `mergerfs --version`
- `findmnt -t fuse.mergerfs -o TARGET,SOURCE,OPTIONS`
- terminal output from `MFP_DEBUG=1 mergerfs-panel` while reproducing

Redact paths you consider private. Screenshots help for layout problems.

## Requesting features

Open an issue with the feature template and describe the problem before the solution.
Explicitly out of scope: file browsing, RAID/parity, fstab/systemd editing, running
as root, and per-file distribution management.

## Development setup

```bash
git clone https://github.com/ztomasic/mergerfs-panel.git
cd mergerfs-panel
make test
make run
```

Dependencies are listed in [docs/INSTALL.md](docs/INSTALL.md). The project intentionally
depends only on the standard library and PyGObject; new runtime dependencies need a
discussion in an issue first.

## Pull requests

- Keep changes focused. One logical change per pull request.
- Add or update tests for behaviour changes. `make test` must pass.
- Run `mergerfs-panel --self-test` (or `make self-test`) if you touched the UI.
- Update the relevant document when behaviour, configuration, packaging, or
  limitations change.
- Do not commit build artifacts (`dist/`, `build/`, `__pycache__`, `*.egg-info`).
- Match the style of the surrounding code: standard library + PyGObject, type hints on
  public functions, user-facing messages that say what to do next.

Commit messages: short imperative subject, optional body explaining the why. Example:

```
Add branch removal verification

Read the branch list back after a removal so silent no-ops (for
example the unsupported -[...] form) are caught.
```

## Packaging changes

A change to `app/pyproject.toml`, `app/data/`, or the version must be reflected in
every package. See the version bump checklist in
[docs/PACKAGING.md](docs/PACKAGING.md#version-bump-checklist).

## License

Contributions are accepted under the MIT license used by the project
(`app/LICENSE`).
