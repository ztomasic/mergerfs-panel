"""Tests for the boot restore service and headless restore command."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from mergerfs_panel import backend, boot
from mergerfs_panel.config import Config


class UnitTextTests(unittest.TestCase):
    def test_unit_contains_restore_command(self):
        text = boot.unit_text(["/usr/bin/python3", "-m", "mergerfs_panel"], wait_seconds=42)
        self.assertIn(
            "ExecStart=/usr/bin/python3 -m mergerfs_panel --restore-pools --wait 42", text
        )
        self.assertIn("Type=oneshot", text)
        self.assertIn("TimeoutStartSec=102", text)
        self.assertIn("WantedBy=default.target", text)

    def test_environment_and_quoting(self):
        text = boot.unit_text(
            ["/opt/My Apps/python3"],
            10,
            {"PYTHONPATH": "/opt/My Apps/src"},
        )
        self.assertIn('Environment=PYTHONPATH="/opt/My Apps/src"', text)
        self.assertIn('ExecStart="/opt/My Apps/python3" --restore-pools --wait 10', text)

    def test_escapes_systemd_specifiers(self):
        text = boot.unit_text(["/opt/100%/app$"], 1)
        self.assertIn('"/opt/100%%/app$$"', text)

    def test_unit_path_follows_xdg_config_home(self):
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": temporary}):
                expected = Path(temporary) / "systemd/user" / boot.UNIT_NAME
                self.assertEqual(boot.unit_path(), expected)


class ServiceInstallTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="mfp-unit-")
        self.unit = Path(self.root) / "systemd/user" / boot.UNIT_NAME
        self.ok = subprocess.CompletedProcess([], 0, "", "")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_enable_writes_unit_and_enables_lingering(self):
        with mock.patch.object(boot, "unit_path", return_value=self.unit), \
             mock.patch.object(boot, "supported", return_value=True), \
             mock.patch.object(boot, "_systemctl", return_value=self.ok) as systemctl, \
             mock.patch.object(boot, "linger_enabled", return_value=False), \
             mock.patch.object(boot, "_enable_linger", return_value=(True, "")), \
             mock.patch.object(
                 boot,
                 "_restore_command",
                 return_value=(["/usr/bin/python3", "-m", "mergerfs_panel"], {}),
             ):
            ok, message = boot.enable(wait_seconds=30)

        self.assertTrue(ok, message)
        text = self.unit.read_text(encoding="utf-8")
        self.assertIn("ExecStart=/usr/bin/python3 -m mergerfs_panel --restore-pools --wait 30", text)
        calls = [call.args for call in systemctl.call_args_list]
        self.assertIn(("daemon-reload",), calls)
        self.assertIn(("enable", boot.UNIT_NAME), calls)

    def test_enable_rolls_back_when_lingering_is_denied(self):
        with mock.patch.object(boot, "unit_path", return_value=self.unit), \
             mock.patch.object(boot, "supported", return_value=True), \
             mock.patch.object(boot, "_systemctl", return_value=self.ok), \
             mock.patch.object(boot, "linger_enabled", return_value=False), \
             mock.patch.object(boot, "_enable_linger", return_value=(False, "denied")), \
             mock.patch.object(
                 boot,
                 "_restore_command",
                 return_value=(["/usr/bin/python3", "-m", "mergerfs_panel"], {}),
             ):
            ok, message = boot.enable()

        self.assertFalse(ok)
        self.assertIn("denied", message)
        self.assertFalse(self.unit.exists())

    def test_disable_removes_unit(self):
        self.unit.parent.mkdir(parents=True)
        self.unit.write_text("[Unit]\n", encoding="utf-8")
        with mock.patch.object(boot, "unit_path", return_value=self.unit), \
             mock.patch.object(boot, "supported", return_value=True), \
             mock.patch.object(boot, "_systemctl", return_value=self.ok):
            ok, message = boot.disable()

        self.assertTrue(ok, message)
        self.assertFalse(self.unit.exists())


@unittest.skipUnless(backend.mergerfs_available(), "mergerfs is not installed")
class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="mfp-restore-")
        self.disk1 = os.path.join(self.root, "disk1")
        self.disk2 = os.path.join(self.root, "disk2")
        os.makedirs(self.disk1)
        os.makedirs(self.disk2)
        self.pool = os.path.join(self.root, "pool")
        self.config = Config(os.path.join(self.root, "config.json"))
        self.messages: list[str] = []

    def tearDown(self):
        if backend.is_mounted(self.pool):
            try:
                backend.unmount_pool(self.pool)
            except backend.MergerfsError:
                pass
        shutil.rmtree(self.root, ignore_errors=True)

    def _log(self, message: str) -> None:
        self.messages.append(message)

    def test_mounts_all_branches(self):
        self.config.record_pool(self.pool, "pool", [self.disk1, self.disk2])
        code = boot.restore_pools(self.config, wait_seconds=0, log=self._log)
        self.assertEqual(code, 0)
        self.assertTrue(backend.is_mounted(self.pool))
        self.assertEqual(
            sorted(branch.path for branch in backend.read_branches(self.pool)),
            sorted([self.disk1, self.disk2]),
        )

    def test_mounts_partial_when_branch_is_missing(self):
        missing = os.path.join(self.root, "gone")
        self.config.record_pool(self.pool, "pool", [self.disk1, missing])
        code = boot.restore_pools(self.config, wait_seconds=0, log=self._log)
        self.assertEqual(code, 0)
        self.assertTrue(backend.is_mounted(self.pool))
        self.assertEqual(
            [branch.path for branch in backend.read_branches(self.pool)], [self.disk1]
        )
        self.assertTrue(any("missing" in message for message in self.messages))

    def test_waits_for_a_late_branch(self):
        late = os.path.join(self.root, "late")
        self.config.record_pool(self.pool, "pool", [late])
        threading.Timer(0.4, lambda: os.makedirs(late, exist_ok=True)).start()
        code = boot.restore_pools(self.config, wait_seconds=10, poll_interval=0.1, log=self._log)
        self.assertEqual(code, 0)
        self.assertTrue(backend.is_mounted(self.pool))
        self.assertEqual([branch.path for branch in backend.read_branches(self.pool)], [late])

    def test_skips_pools_that_are_already_mounted(self):
        self.config.record_pool(self.pool, "pool", [self.disk1])
        boot.restore_pools(self.config, wait_seconds=0, log=self._log)
        self.messages.clear()
        code = boot.restore_pools(self.config, wait_seconds=0, log=self._log)
        self.assertEqual(code, 0)
        self.assertTrue(any("already mounted" in message for message in self.messages))

    def test_ignores_pools_with_autostart_disabled(self):
        self.config.record_pool(self.pool, "pool", [self.disk1], autostart=False)
        code = boot.restore_pools(self.config, wait_seconds=0, log=self._log)
        self.assertEqual(code, 0)
        self.assertFalse(backend.is_mounted(self.pool))

    def test_no_pools_is_not_an_error(self):
        code = boot.restore_pools(self.config, wait_seconds=0, log=self._log)
        self.assertEqual(code, 0)
        self.assertTrue(any("no pools" in message for message in self.messages))


if __name__ == "__main__":
    unittest.main()
