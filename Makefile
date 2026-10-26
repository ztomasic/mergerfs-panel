VERSION := $(shell sed -n 's/^version = "\([^"]*\)"/\1/p' app/pyproject.toml | head -n1)
RUN := PYTHONPATH=app/src python3 -m mergerfs_panel

.PHONY: help run test self-test tarball rpm deb install uninstall clean

help:
	@echo "make run        - run from the source tree"
	@echo "make test       - run unit and live mergerfs tests"
	@echo "make self-test  - construct the window and exit (GUI smoke test)"
	@echo "make tarball    - build dist/mergerfs-panel-$(VERSION).tar.gz"
	@echo "make rpm        - build the Fedora RPM (needs rpm-build, pyproject-rpm-macros)"
	@echo "make deb        - build a Debian package (needs debhelper, dh-python)"
	@echo "make install    - install with distro/universal/install.sh (PREFIX=/usr/local)"
	@echo "make uninstall  - remove the universal install"

run:
	$(RUN)

test:
	PYTHONPATH=app/src python3 -m unittest discover -s app/tests -v

self-test:
	GDK_BACKEND=x11 PYTHONPATH=app/src python3 -m mergerfs_panel --self-test

tarball:
	distro/build-tarball.sh

rpm: tarball
	mkdir -p $(HOME)/rpmbuild/SOURCES
	cp dist/mergerfs-panel-$(VERSION).tar.gz $(HOME)/rpmbuild/SOURCES/
	rpmbuild -bb distro/fedora/mergerfs-panel.spec

deb: tarball
	distro/debian/build.sh

install:
	PREFIX=$${PREFIX:-/usr/local} distro/universal/install.sh

uninstall:
	PREFIX=$${PREFIX:-/usr/local} distro/universal/uninstall.sh

clean:
	rm -rf dist
	find app -name '__pycache__' -type d -prune -exec rm -rf {} +
	find app -name '*.pyc' -delete
