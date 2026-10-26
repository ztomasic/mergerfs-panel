# Installation

## Requirements

| Component | Minimum | Notes |
|---|---|---|
| Linux | — | Any distribution with FUSE and UDisks2 |
| Python | 3.9 | Uses only the standard library plus PyGObject |
| GTK | 4.10 | `Gtk.AlertDialog` is used for confirmations |
| PyGObject | 3.42 | Distribution package, not installable from PyPI |
| UDisks2 | 2.9 | Disk enumeration, mounting, polkit authentication |
| mergerfs | 2.x | Only needed to create pools |

Package names by distribution:

| | Fedora | Debian / Ubuntu | Arch |
|---|---|---|---|
| GTK + bindings | `gtk4`, `python3-gobject` | `gir1.2-gtk-4.0`, `python3-gi` | `gtk4`, `python-gobject` |
| mergerfs | upstream RPM | upstream `.deb` | AUR (`mergerfs`) |

`mergerfs` is not in Fedora's repositories and is not packaged by this project.
Download the RPM for your Fedora release from
<https://github.com/trapexit/mergerfs/releases> and install it with `dnf`.

GTK 4.10 means Debian 13+ and Ubuntu 24.04+. Distributions with older GTK can still
build the app, but dialogs (confirmations and errors) will fail at runtime.

## Fedora (RPM)

Build dependencies:

```bash
sudo dnf install rpm-build pyproject-rpm-macros python3-devel \
                 desktop-file-utils appstream
```

Build and install:

```bash
git clone https://github.com/ztomasic/mergerfs-panel.git
cd mergerfs-panel
make rpm
sudo dnf install ~/rpmbuild/RPMS/noarch/mergerfs-panel-*.noarch.rpm
```

`make rpm` builds the source tarball, copies it into `~/rpmbuild/SOURCES`, and runs
`rpmbuild -bb`. The package is `noarch` and pulls in `python3-gobject` and `gtk4`.
`mergerfs` is a weak dependency (`Recommends`) because it has no Fedora package.

Uninstall:

```bash
sudo dnf remove mergerfs-panel
```

## Debian / Ubuntu

Build dependencies:

```bash
sudo apt install debhelper dpkg-dev dh-python python3-all python3-setuptools
```

Build and install:

```bash
git clone https://github.com/ztomasic/mergerfs-panel.git
cd mergerfs-panel
make deb
sudo apt install dist/mergerfs-panel_*.deb
```

The package depends on `python3-gi` and `gir1.2-gtk-4.0` and recommends `mergerfs`.
Install mergerfs from its upstream `.deb` if `apt` has no candidate.

Uninstall:

```bash
sudo apt remove mergerfs-panel
```

## Arch

```bash
git clone https://github.com/ztomasic/mergerfs-panel.git
cd mergerfs-panel
make tarball
cd distro/arch
cp ../../dist/mergerfs-panel-*.tar.gz .
makepkg -si
```

Build dependencies come from `makedepends` in the PKGBUILD. Runtime dependencies
are `python`, `python-gobject`, and `gtk4`; `mergerfs` is an optional dependency.

Uninstall:

```bash
sudo pacman -R mergerfs-panel
```

## Any distribution (universal installer)

The universal installer copies the Python package, launcher, desktop entry, icon,
and AppStream metadata into a prefix. It needs no packaging tools.

```bash
# System-wide (writes to /usr/local)
sudo ./distro/universal/install.sh

# Per-user, no root (requires ~/.local/bin in PATH)
PREFIX="$HOME/.local" ./distro/universal/install.sh

# Stage a package tree for another tool
DESTDIR=/tmp/pkg PREFIX=/usr ./distro/universal/install.sh
```

Uninstall with the same `PREFIX` (and `DESTDIR`, if used):

```bash
sudo ./distro/universal/uninstall.sh
PREFIX="$HOME/.local" ./distro/universal/uninstall.sh
```

## From the source tree

```bash
sudo apt install python3-gi gir1.2-gtk-4.0   # or the Fedora equivalents
make run
```

Equivalently: `PYTHONPATH=app/src python3 -m mergerfs_panel`.

## Verify the installation

```bash
mergerfs-panel --version          # mergerfs-panel 0.1.0
desktop-file-validate /usr/share/applications/mergerfs-panel.desktop
```

Start it from the application menu, or run `mergerfs-panel`. If mergerfs is not
installed, the disk list still works; creating a pool reports a clear error.

## Making a pool available to other users and services

A pool mounted by the app belongs to the user who mounted it. Other users — and
system services such as a web server running as `www-data` or `apache` — cannot
read it unless the mount was created with `allow_other` and `/etc/fuse.conf`
contains `user_allow_other` (root-run mounts are exempt from that file).

For a service, prefer a boot-time mount owned by root at a stable path:

```fstab
/run/media/you/disk1:/run/media/you/disk2  /srv/media  mergerfs  defaults,nofail,allow_other,category.create=mfs,minfreespace=4G  0 0
```

Then point the service at `/srv/media`. See [USAGE.md](USAGE.md) for the caveats
about disks that are not mounted yet at boot.
