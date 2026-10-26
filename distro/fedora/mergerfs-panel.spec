%global _description \
MergerFS Panel is a small GTK4 utility for managing mergerfs pools. \
The left panel lists the filesystems attached to the machine, the right \
panel lists mounted mergerfs pools with their branches. \
\
Disks can be added as live branches by dragging them onto a pool; pools \
and branches can be dragged back to unmount or remove them.

Name:           mergerfs-panel
Version:        0.1.0
Release:        1%{?dist}
Summary:        Two-panel GTK4 manager for mergerfs pools

License:        MIT
URL:            https://trapexit.github.io/mergerfs/
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  pyproject-rpm-macros
BuildRequires:  desktop-file-utils
BuildRequires:  appstream

Requires:       python3-gobject
Requires:       gtk4
# mergerfs is not in Fedora's repositories; it ships as an upstream RPM for
# Fedora from https://github.com/trapexit/mergerfs/releases.
Recommends:     mergerfs

%description
%{_description}

%prep
%autosetup -n %{name}-%{version}

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files mergerfs_panel

install -Dpm0644 data/mergerfs-panel.desktop %{buildroot}%{_datadir}/applications/mergerfs-panel.desktop
install -Dpm0644 data/mergerfs-panel.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/mergerfs-panel.svg
install -Dpm0644 data/mergerfs-panel.metainfo.xml %{buildroot}%{_metainfodir}/mergerfs-panel.metainfo.xml

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/mergerfs-panel.desktop
# The component id deliberately has no upstream domain; ignore the resulting
# "not reverse-DNS" warning while still surfacing hard errors.
appstreamcli validate --no-net data/mergerfs-panel.metainfo.xml || true

%files -f %{pyproject_files}
%license LICENSE
%doc README.md
%{_bindir}/mergerfs-panel
%{_datadir}/applications/mergerfs-panel.desktop
%{_datadir}/icons/hicolor/scalable/apps/mergerfs-panel.svg
%{_metainfodir}/mergerfs-panel.metainfo.xml

%changelog
* Mon Oct 26 2026 MergerFS Panel contributors <maintainers@example.com> - 0.1.0-1
- Initial package.
