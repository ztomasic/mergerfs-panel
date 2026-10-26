# Packaging

The repository separates application code from distribution packaging:

```
app/                 source tarball contents
  pyproject.toml
  src/mergerfs_panel/
  data/              desktop entry, icon, AppStream metadata
  tests/
  LICENSE
  README.md (copied in by the tarball script)
distro/
  build-tarball.sh   creates dist/mergerfs-panel-<version>.tar.gz
  fedora/            RPM spec
  debian/            Debian packaging + build.sh
  arch/              PKGBUILD
  universal/         install.sh / uninstall.sh for any distribution
```

All package builds consume the same source tarball. The tarball has a single
`mergerfs-panel-<version>/` top-level directory containing `pyproject.toml`, `src/`,
`data/`, `tests/`, `LICENSE`, and `README.md`.

## Source tarball

```bash
distro/build-tarball.sh              # writes dist/mergerfs-panel-<version>.tar.gz
distro/build-tarball.sh /tmp/output  # custom output directory
```

The script reads the version from `pyproject.toml`, copies `app/`, optionally adds
`README.md` and `docs/`, and removes `__pycache__`, `build/`, and `*.egg-info`.

## Fedora RPM

`distro/fedora/mergerfs-panel.spec` is a noarch package built with the Python
pyproject macros:

```bash
sudo dnf install rpm-build pyproject-rpm-macros python3-devel desktop-file-utils appstream
make rpm
```

Notes:

- `BuildRequires: pyproject-rpm-macros` provides `%pyproject_wheel`,
  `%pyproject_install`, and `%pyproject_save_files`.
- `Requires: python3-gobject`, `Requires: gtk4`; `Recommends: mergerfs`, because
  mergerfs has no Fedora package and must come from upstream.
- The `.desktop` file, icon, and AppStream metadata are installed explicitly.
- `%check` validates the desktop entry. AppStream validation is informational: the
  component id intentionally has no upstream domain, which the validator reports as a
  warning.

## Debian / Ubuntu

`distro/debian/` is a standard debhelper + dh-python package. `debian/build.sh`
unpacks the tarball, copies the packaging directory in, and runs
`dpkg-buildpackage -us -uc -b`:

```bash
sudo apt install debhelper dpkg-dev dh-python python3-all python3-setuptools
make deb
```

`debian/mergerfs-panel.install` installs the desktop entry, icon, and metadata;
dh_python3 installs the module and the `mergerfs-panel` script. `debian/rules`
overrides `dh_auto_test` to run the unit tests with `PYTHONPATH=src`.

## Arch

`distro/arch/PKGBUILD` builds a wheel with `python-build` and installs it with
`python-installer`:

```bash
make tarball
cd distro/arch
cp ../../dist/mergerfs-panel-*.tar.gz .
makepkg -si
```

The PKGBUILD uses `sha256sums=('SKIP')` because it consumes a locally built tarball;
replace that with a real checksum before publishing a binary package.

## Universal installer

`distro/universal/install.sh` works on any distribution with Python, PyGObject and
GTK4. It copies the package to `$PREFIX/lib/mergerfs-panel`, writes a small launcher
that sets `PYTHONPATH`, and installs the desktop entry, icon, and metadata.

```bash
sudo ./distro/universal/install.sh                        # /usr/local
PREFIX="$HOME/.local" ./distro/universal/install.sh       # per user
DESTDIR=/tmp/pkg PREFIX=/usr ./distro/universal/install.sh  # staged
```

`PREFIX` and `DESTDIR` must be passed to `uninstall.sh` as well.

## Version bump checklist

1. `app/pyproject.toml` — `version`.
2. `CHANGELOG.md` — add a section.
3. `distro/fedora/mergerfs-panel.spec` — `Version`, `Release` reset to 1, new
   `%changelog` entry.
4. `distro/debian/changelog` — new entry and version.
5. `distro/arch/PKGBUILD` — `pkgver`, `pkgrel=1`.
6. `make tarball` and rebuild each package.
7. Commit, tag (`vX.Y.Z`), push the tag, and create a GitHub release with the
   tarball (and optionally the RPM/deb).

## Validation before a release

```bash
make test
desktop-file-validate app/data/mergerfs-panel.desktop
appstreamcli validate --no-net app/data/mergerfs-panel.metainfo.xml || true
make tarball
make rpm                      # if rpm-build is installed
PREFIX=/tmp/stage ./distro/universal/install.sh
/tmp/stage/bin/mergerfs-panel --version
PREFIX=/tmp/stage ./distro/universal/uninstall.sh
```

The test suite includes live mergerfs tests that mount a temporary pool in `/tmp` and
are skipped when mergerfs or FUSE is unavailable.

## CI

`.github/workflows/ci.yml` runs on every push and pull request:

- installs PyGObject, GTK4, desktop-file-utils, and mergerfs (when available);
- runs the unit and integration tests;
- validates the desktop entry;
- builds a wheel in a virtual environment.

The workflow does not build distribution packages; those need a Fedora or Debian
environment.
