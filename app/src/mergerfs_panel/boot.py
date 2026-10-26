"""Boot-time pool restore.

The GUI can install a systemd *user* service that runs the headless
``--restore-pools`` command. Enabling lingering for the user makes that service
start at boot instead of at login, so pools are restored without the app.

Branch filesystems have to be mounted before mergerfs can use them. The restore
command therefore waits for the configured branch directories, up to a timeout,
before mounting with whatever is available.
"""

from __future__ import annotations

import getpass
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import backend
from .config import Config

UNIT_NAME = "mergerfs-panel-restore.service"
UNIT_DESCRIPTION = "Restore mergerfs pools managed by MergerFS Panel"
PROJECT_URL = "https://github.com/ztomasic/mergerfs-panel"
DEFAULT_WAIT = 600
POLL_INTERVAL = 2.0

_SAFE_ARGUMENT = re.compile(r"^[A-Za-z0-9_@%+=:,./-]+$")


def config_home() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root


def unit_path() -> Path:
    return config_home() / "systemd" / "user" / UNIT_NAME


def _systemd_quote(argument: str) -> str:
    if _SAFE_ARGUMENT.match(argument) and "%" not in argument:
        return argument
    escaped = (
        argument.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "$$")
        .replace("%", "%%")
    )
    return f'"{escaped}"'


def unit_text(command: list[str], wait_seconds: int = DEFAULT_WAIT, environment: dict[str, str] | None = None) -> str:
    lines = [
        "[Unit]",
        f"Description={UNIT_DESCRIPTION}",
        f"Documentation={PROJECT_URL}",
        "After=default.target",
        "",
        "[Service]",
        "Type=oneshot",
    ]
    for key, value in (environment or {}).items():
        lines.append(f"Environment={key}={_systemd_quote(value)}")

    exec_arguments = [*command, "--restore-pools", "--wait", str(wait_seconds)]
    lines.append("ExecStart=" + " ".join(_systemd_quote(part) for part in exec_arguments))
    lines.append(f"TimeoutStartSec={wait_seconds + 60}")
    lines.append("Nice=10")
    lines.append("IOSchedulingClass=idle")
    lines.append("")
    lines.append("[Install]")
    lines.append("WantedBy=default.target")
    lines.append("")
    return "\n".join(lines)


def _restore_command() -> tuple[list[str], dict[str, str]]:
    """Command for the unit, pointed at this exact package.

    Pinning PYTHONPATH keeps the service on the same code as the app that
    generated the unit, whether it was installed system-wide, in a prefix, or
    run from a source tree. Relying on site-packages could silently pick up an
    older installed version.
    """
    package_parent = Path(__file__).resolve().parent.parent
    return [sys.executable, "-m", "mergerfs_panel"], {"PYTHONPATH": str(package_parent)}


def _systemctl(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", "--user", *arguments],
        capture_output=True,
        text=True,
        timeout=30,
    )


def supported() -> bool:
    if not shutil.which("systemctl"):
        return False
    try:
        return _systemctl("show-environment").returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def service_enabled() -> bool:
    try:
        result = _systemctl("is-enabled", UNIT_NAME)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip() == "enabled"


def linger_enabled(user: str | None = None) -> bool:
    if not shutil.which("loginctl"):
        return False
    user = user or getpass.getuser()
    try:
        result = subprocess.run(
            ["loginctl", "show-user", user, "-p", "Linger", "--value"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip() == "yes"


def enabled() -> bool:
    return service_enabled() and linger_enabled()


def _enable_linger(user: str) -> tuple[bool, str]:
    try:
        direct = subprocess.run(
            ["loginctl", "enable-linger", user],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        direct = None
        direct_error = str(exc)
    else:
        if direct.returncode == 0:
            return True, ""
        direct_error = direct.stderr.strip() or f"status {direct.returncode}"

    if not shutil.which("pkexec"):
        return False, direct_error

    try:
        elevated = subprocess.run(
            ["pkexec", "loginctl", "enable-linger", user],
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if elevated.returncode == 0:
        return True, ""
    return False, elevated.stderr.strip() or direct_error


def _remove_unit() -> None:
    try:
        _systemctl("disable", "--now", UNIT_NAME)
        unit_path().unlink(missing_ok=True)
        _systemctl("daemon-reload")
    except (OSError, subprocess.TimeoutExpired):
        pass


def enable(wait_seconds: int = DEFAULT_WAIT) -> tuple[bool, str]:
    """Install and enable the boot service, including lingering."""
    if not supported():
        return False, "systemd user session is not available"

    command, environment = _restore_command()
    path = unit_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(unit_text(command, wait_seconds, environment), encoding="utf-8")
    except OSError as exc:
        return False, f"cannot write {path}: {exc}"

    reload_result = _systemctl("daemon-reload")
    if reload_result.returncode != 0:
        _remove_unit()
        return False, reload_result.stderr.strip() or "systemctl daemon-reload failed"

    enable_result = _systemctl("enable", UNIT_NAME)
    if enable_result.returncode != 0:
        _remove_unit()
        return (
            False,
            enable_result.stderr.strip() or f"could not enable {UNIT_NAME}",
        )

    if not linger_enabled():
        granted, message = _enable_linger(getpass.getuser())
        if not granted:
            _remove_unit()
            return False, f"could not enable lingering: {message}"

    return True, "Pools will be restored at boot"


def disable() -> tuple[bool, str]:
    """Remove the boot service. Lingering itself is left untouched."""
    if not supported():
        return False, "systemd user session is not available"

    result = _systemctl("disable", "--now", UNIT_NAME)
    unit_path().unlink(missing_ok=True)
    _systemctl("daemon-reload")

    message = (result.stderr or "").lower()
    tolerated = ("not loaded", "does not exist", "no such file")
    if result.returncode != 0 and not any(marker in message for marker in tolerated):
        return False, result.stderr.strip() or "could not disable the service"
    return True, "Boot restore disabled"


def _configured_pools(config: Config) -> list[tuple[str, list[str], str]]:
    pools: list[tuple[str, list[str], str]] = []
    for mountpoint, entry in sorted(config.pools.items()):
        if not isinstance(entry, dict) or not entry.get("autostart", True):
            continue
        branches = [branch for branch in entry.get("branches", []) if branch]
        if not branches:
            continue
        pools.append((mountpoint, branches, str(entry.get("options", ""))))
    return pools


def _mount_one(
    mountpoint: str,
    branches: list[str],
    options: str,
    log,
    missing: list[str] | None = None,
) -> int:
    try:
        os.makedirs(mountpoint, exist_ok=True)
        backend.mount_pool(branches, mountpoint, options)
    except (backend.MergerfsError, OSError) as exc:
        log(f"{mountpoint}: cannot mount: {exc}")
        return 1
    suffix = f" (missing: {', '.join(missing)})" if missing else ""
    log(f"{mountpoint}: mounted{suffix}")
    return 0


def restore_pools(
    config: Config | None = None,
    wait_seconds: int = DEFAULT_WAIT,
    poll_interval: float = POLL_INTERVAL,
    log=print,
) -> int:
    """Mount configured pools, waiting for their branches to appear.

    A pool is mounted as soon as all of its configured branches exist. When the
    deadline passes, remaining pools are mounted with whatever branches are
    available. Pools with no branch directory at all are skipped.

    Returns 0 when the run was handled (including skipped pools), 1 when a mount
    attempt failed.
    """
    config = config or Config()
    pools = _configured_pools(config)
    if not pools:
        log("no pools configured for boot restore")
        return 0

    pending: dict[str, tuple[list[str], str]] = {}
    for mountpoint, branches, options in pools:
        if backend.is_mounted(mountpoint):
            log(f"{mountpoint}: already mounted")
            continue
        pending[mountpoint] = (branches, options)

    if not pending:
        return 0

    failures = 0
    deadline = time.monotonic() + max(0, int(wait_seconds))
    while pending and time.monotonic() < deadline:
        for mountpoint, (branches, options) in list(pending.items()):
            if not all(os.path.isdir(branch) for branch in branches):
                continue
            pending.pop(mountpoint)
            failures += _mount_one(mountpoint, branches, options, log)
        if pending:
            time.sleep(max(0.1, poll_interval))

    for mountpoint, (branches, options) in list(pending.items()):
        available = [branch for branch in branches if os.path.isdir(branch)]
        if not available:
            log(f"{mountpoint}: skipped, no branch directories exist")
            continue
        missing = [branch for branch in branches if branch not in available]
        failures += _mount_one(mountpoint, available, options, log, missing)

    return 1 if failures else 0
