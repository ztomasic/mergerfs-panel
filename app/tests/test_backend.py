"""Tests for the non-GUI core. Includes a real mergerfs integration test."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from mergerfs_panel import backend
from mergerfs_panel.config import Config

MOUNTINFO_SAMPLE = """\
36 35 98:0 /mnt1 /mnt2 rw,noatime master:1 - ext3 /dev/root rw,errors=continue
42 35 0:91 / /run/user/1000/gvfs rw,nosuid,nodev,relatime - fuse.gvfsd-fuse gvfsd-fuse rw,user_id=1000
43 35 0:92 / /home/user/My\\040Pool rw,relatime - fuse.mergerfs mergerfs-test rw,user_id=1000,group_id=1000
"""


class MountinfoTests(unittest.TestCase):
    def test_parses_fields(self):
        mounts = backend.parse_mountinfo(MOUNTINFO_SAMPLE)
        self.assertEqual(len(mounts), 3)
        first = mounts[0]
        self.assertEqual(first["mountpoint"], "/mnt2")
        self.assertEqual(first["fstype"], "ext3")
        self.assertEqual(first["source"], "/dev/root")

    def test_unescapes_spaces(self):
        mounts = backend.parse_mountinfo(MOUNTINFO_SAMPLE)
        self.assertEqual(mounts[2]["mountpoint"], "/home/user/My Pool")

    def test_finds_only_mergerfs(self):
        mounts = backend.parse_mountinfo(MOUNTINFO_SAMPLE)
        mergerfs = [m for m in mounts if m["fstype"] == backend.MERGERFS_FSTYPE]
        self.assertEqual(len(mergerfs), 1)
        self.assertEqual(mergerfs[0]["source"], "mergerfs-test")


class BranchParsingTests(unittest.TestCase):
    def test_parses_paths_and_flags(self):
        branches = backend.parse_branches("/mnt/a=RW:/mnt/b=RO:/mnt/c")
        self.assertEqual([b.path for b in branches], ["/mnt/a", "/mnt/b", "/mnt/c"])
        self.assertEqual([b.flags for b in branches], ["RW", "RO", "RW"])

    def test_round_trip_omits_default_flag(self):
        branches = backend.parse_branches("/mnt/a:/mnt/b=RO,1234")
        self.assertEqual(backend.branches_to_spec(branches), "/mnt/a:/mnt/b=RO,1234")

    def test_empty_spec(self):
        self.assertEqual(backend.parse_branches(""), [])


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="mfp-validate-")
        self.pool = os.path.join(self.root, "pool")
        self.branch = os.path.join(self.root, "disk1")
        os.makedirs(self.pool)
        os.makedirs(self.branch)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_accepts_a_separate_directory(self):
        self.assertIsNone(backend.validate_branch(self.pool, self.branch))

    def test_rejects_the_mountpoint_itself(self):
        self.assertIsNotNone(backend.validate_branch(self.pool, self.pool))

    def test_rejects_branch_inside_pool(self):
        inside = os.path.join(self.pool, "nested")
        os.makedirs(inside)
        self.assertIn("inside the pool", backend.validate_branch(self.pool, inside) or "")

    def test_rejects_branch_that_contains_the_pool(self):
        problem = backend.validate_branch(self.pool, self.root)
        self.assertIn("contains the pool", problem or "")

    def test_rejects_root(self):
        self.assertIsNotNone(backend.validate_branch(self.pool, "/"))

    def test_rejects_duplicates(self):
        existing = [backend.Branch(self.branch)]
        self.assertIn("already a branch", backend.validate_branch(self.pool, self.branch, existing) or "")

    def test_rejects_missing_directory(self):
        self.assertIn(
            "not a directory",
            backend.validate_branch(self.pool, os.path.join(self.root, "nope")) or "",
        )


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="mfp-config-")
        self.path = os.path.join(self.root, "config.json")
        self.config = Config(self.path)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_records_and_reloads(self):
        mountpoint = os.path.join(self.root, "pool")
        self.config.record_pool(mountpoint, "media", ["/mnt/d1"], "category.create=mfs")
        reloaded = Config(self.path)
        self.assertTrue(reloaded.is_managed(mountpoint))
        self.assertEqual(reloaded.entry(mountpoint)["branches"], ["/mnt/d1"])

    def test_updates_branches(self):
        mountpoint = os.path.join(self.root, "pool")
        self.config.record_pool(mountpoint, "media", ["/mnt/d1"])
        self.assertTrue(self.config.update_branches(mountpoint, ["/mnt/d1", "/mnt/d2"]))
        self.assertEqual(self.config.entry(mountpoint)["branches"], ["/mnt/d1", "/mnt/d2"])

    def test_autostart_skips_missing_branches(self):
        mountpoint = os.path.join(self.root, "pool")
        existing = os.path.join(self.root, "existing")
        os.makedirs(existing)
        self.config.record_pool(mountpoint, "media", [existing, os.path.join(self.root, "gone")])
        entries = self.config.autostart_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["branches"], [existing])

    def test_unknown_updates_are_reported(self):
        self.assertFalse(self.config.update_branches(os.path.join(self.root, "other"), ["/x"]))


@unittest.skipUnless(backend.mergerfs_available(), "mergerfs is not installed")
class LivePoolTests(unittest.TestCase):
    """Exercises the real xattr interface against a throwaway pool."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="mfp-live-")
        self.branches = [os.path.join(self.root, f"disk{n}") for n in (1, 2, 3)]
        for path in self.branches:
            os.makedirs(path)
        self.mountpoint = os.path.join(self.root, "pool")
        os.makedirs(self.mountpoint)
        try:
            backend.mount_pool(self.branches[:2], self.mountpoint)
        except backend.MergerfsError as exc:
            shutil.rmtree(self.root, ignore_errors=True)
            self.skipTest(f"cannot mount in this environment: {exc}")

    def tearDown(self):
        try:
            backend.unmount_pool(self.mountpoint)
        except backend.MergerfsError:
            pass
        shutil.rmtree(self.root, ignore_errors=True)

    def test_pool_is_listed(self):
        pools = backend.list_pools()
        match = [pool for pool in pools if pool.mountpoint == self.mountpoint]
        self.assertEqual(len(match), 1)
        self.assertEqual(
            sorted(branch.path for branch in match[0].branches),
            sorted(self.branches[:2]),
        )

    def test_add_and_remove_branch_live(self):
        backend.add_branch(self.mountpoint, self.branches[2])
        self.assertIn(self.branches[2], [branch.path for branch in backend.read_branches(self.mountpoint)])

        with open(os.path.join(self.mountpoint, "probe.txt"), "w", encoding="utf-8") as handle:
            handle.write("hello")
        self.assertTrue(
            any(os.path.exists(os.path.join(path, "probe.txt")) for path in self.branches)
        )

        backend.remove_branch(self.mountpoint, self.branches[2])
        self.assertNotIn(
            self.branches[2], [branch.path for branch in backend.read_branches(self.mountpoint)]
        )

    def test_validation_is_applied_by_the_caller(self):
        problem = backend.validate_branch(self.mountpoint, self.mountpoint)
        self.assertIsNotNone(problem)

    def test_rejects_empty_pool(self):
        with self.assertRaises(backend.MergerfsError):
            backend.replace_branches(self.mountpoint, [])


class UDisksTests(unittest.TestCase):
    def test_lists_disks_if_the_system_bus_is_available(self):
        try:
            client = backend.UDisks()
            disks = client.list_disks()
        except Exception as exc:  # noqa: BLE001 - CI containers often lack udisks2
            self.skipTest(f"UDisks2 unavailable: {exc}")
        self.assertIsInstance(disks, list)
        for disk in disks:
            self.assertTrue(disk.device.startswith("/dev/"))


if __name__ == "__main__":
    unittest.main()
