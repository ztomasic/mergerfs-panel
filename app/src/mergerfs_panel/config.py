"""Persistent configuration.

mergerfs runtime changes are not persisted by the filesystem itself, so the
app keeps the desired state here and re-applies it on start. The file lives
under $XDG_CONFIG_HOME/mergerfs-panel/config.json.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

APP_DIR = "mergerfs-panel"


def config_home() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / APP_DIR


def default_pool_base() -> Path:
    """Pools are user-owned, so their mountpoints must be user-writable."""
    return Path.home() / "mergerfs"


DEFAULTS: dict = {
    "version": 1,
    "pool_base": str(default_pool_base()),
    "default_options": "category.create=mfs,minfreespace=4G",
    "pools": {},
}


class Config:
    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path) if path else config_home() / "config.json"
        self.data = copy.deepcopy(DEFAULTS)
        self.load()

    # -- lifecycle ---------------------------------------------------------

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, dict):
            return
        self.data.update(raw)
        if not isinstance(self.data.get("pools"), dict):
            self.data["pools"] = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

    # -- accessors ---------------------------------------------------------

    @property
    def pool_base(self) -> Path:
        configured = self.data.get("pool_base") or default_pool_base()
        return Path(configured).expanduser()

    @property
    def default_options(self) -> str:
        return str(self.data.get("default_options") or DEFAULTS["default_options"])

    @property
    def pools(self) -> dict:
        pools = self.data.setdefault("pools", {})
        if not isinstance(pools, dict):
            pools = {}
            self.data["pools"] = pools
        return pools

    # -- mutations ---------------------------------------------------------

    def record_pool(
        self,
        mountpoint: str,
        name: str,
        branches: list[str],
        options: str = "",
        autostart: bool = True,
    ) -> None:
        self.pools[os.path.realpath(mountpoint)] = {
            "name": name,
            "branches": list(branches),
            "options": options,
            "autostart": autostart,
        }
        self.save()

    def update_branches(self, mountpoint: str, branches: list[str]) -> bool:
        entry = self.pools.get(os.path.realpath(mountpoint))
        if entry is None:
            return False
        entry["branches"] = list(branches)
        self.save()
        return True

    def set_autostart(self, mountpoint: str, enabled: bool) -> bool:
        entry = self.pools.get(os.path.realpath(mountpoint))
        if entry is None:
            return False
        entry["autostart"] = bool(enabled)
        self.save()
        return True

    def forget_pool(self, mountpoint: str) -> None:
        self.pools.pop(os.path.realpath(mountpoint), None)
        self.save()

    def is_managed(self, mountpoint: str) -> bool:
        return os.path.realpath(mountpoint) in self.pools

    def entry(self, mountpoint: str) -> dict | None:
        return self.pools.get(os.path.realpath(mountpoint))

    def autostart_entries(self) -> list[dict]:
        entries = []
        for mountpoint, entry in sorted(self.pools.items()):
            if not isinstance(entry, dict) or not entry.get("autostart", True):
                continue
            branches = [branch for branch in entry.get("branches", []) if os.path.isdir(branch)]
            if not branches:
                continue
            entries.append({**entry, "mountpoint": mountpoint, "branches": branches})
        return entries
