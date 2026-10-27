"""tools/publish.py: one serialized publisher per channel (grassfield ADR-0033 h.2 as amended by ADR-0037 g).

Needs pacman's vercmp and bsdtar: runs in the test container (tests/run-in-container.sh).
"""
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import publish  # noqa: E402

HAVE_TOOLS = shutil.which("vercmp") and shutil.which("bsdtar")


def make_db(path, packages):
    """A pacman sync database with only the desc fields publish.py reads."""
    with tarfile.open(path, "w:gz") as tar:
        for name, version in packages.items():
            data = f"%NAME%\n{name}\n\n%VERSION%\n{version}\n\n".encode()
            info = tarfile.TarInfo(f"{name}-{version}/desc")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


@unittest.skipUnless(HAVE_TOOLS, "needs pacman's vercmp and bsdtar (the test container)")
class Publisher(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.releases = os.path.join(self.tmp, "releases")
        self.store = publish.LocalStore(os.path.join(self.tmp, "bucket"), "stable", "x86_64")
        os.makedirs(self.releases)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def release(self, version, packages=None):
        folder = os.path.join(self.releases, version)
        os.makedirs(folder)
        packages = packages or {"grassfield-desktop": version, "grassfield-icons": version}
        make_db(os.path.join(folder, "grassfield.db"), packages)
        for name in ("grassfield.files", "grassfield-notes.json"):
            with open(os.path.join(folder, name), "w") as f:
                f.write(f"{name} {version}\n")
        for name in publish.SNAPSHOT_FILES:
            with open(os.path.join(folder, name + ".sig"), "w") as f:
                f.write(f"sig of {name} {version}\n")
        for name, v in packages.items():
            with open(os.path.join(folder, f"{name}-{v}-x86_64.pkg.tar.zst"), "w") as f:
                f.write(f"{name} {v}\n")
        return folder

    def catalog(self, serial, icon=b"icon-1"):
        folder = os.path.join(self.tmp, f"catalog-{serial}")
        if os.path.exists(folder):
            return folder
        os.makedirs(os.path.join(folder, "catalog"))
        with open(os.path.join(folder, publish.CATALOG_FILE), "w") as f:
            json.dump({"version": 1, "channel": "stable", "serial": serial}, f)
        with open(os.path.join(folder, publish.CATALOG_FILE + ".sig"), "w") as f:
            f.write(f"sig {serial}\n")
        import hashlib
        with open(os.path.join(folder, "catalog", hashlib.sha256(icon).hexdigest() + ".png"), "wb") as f:
            f.write(icon)
        return folder

    def run_once(self, catalog=None, now=1793095200):
        with redirect_stdout(io.StringIO()) as out:
            snapshot = publish.publish(self.store, self.releases, catalog, now=now)
        return snapshot, out.getvalue()

    def current(self):
        snapshot, _ = self.store.read_pointer()
        return self.store.manifest(snapshot)

    def test_first_release_then_catalog_then_release(self):
        self.release("1.0.0-1")
        first, _ = self.run_once()
        self.assertEqual(self.current()["release"], "1.0.0-1")
        self.assertIsNone(self.current()["catalogSerial"])
        self.assertTrue(os.path.exists(os.path.join(self.store.base, "grassfield-desktop-1.0.0-1-x86_64.pkg.tar.zst")))

        # A catalog update keeps the packages, databases and notes.
        second, _ = self.run_once(self.catalog(100), now=1793095300)
        m = self.current()
        self.assertEqual((m["release"], m["catalogSerial"]), ("1.0.0-1", 100))
        with open(self.store.snapshot_path(first, "grassfield.db"), "rb") as a, \
                open(self.store.snapshot_path(second, "grassfield.db"), "rb") as b:
            self.assertEqual(a.read(), b.read())

        # A release keeps the catalog.
        self.release("1.0.1-1")
        self.run_once(self.catalog(100), now=1793095400)
        m = self.current()
        self.assertEqual((m["release"], m["catalogSerial"]), ("1.0.1-1", 100))
        self.assertIn(publish.CATALOG_FILE, m["files"])

    def test_nothing_new_writes_nothing(self):
        self.release("1.0.0-1")
        first, _ = self.run_once(self.catalog(100))
        again, out = self.run_once(self.catalog(100), now=1793099999)
        self.assertIsNone(again)
        self.assertIn("nothing new", out)
        self.assertEqual(self.store.read_pointer()[0], first)

    def test_never_backwards(self):
        self.release("1.0.1-1")
        self.run_once(self.catalog(200))
        # An older catalog (a run built from an older main) and an older build leave the published state as it is.
        shutil.rmtree(os.path.join(self.releases, "1.0.1-1"))
        self.release("1.0.0-1")
        snapshot, out = self.run_once(self.catalog(100), now=1793099999)
        self.assertIsNone(snapshot)
        self.assertIn("older than the published release", out)
        self.assertIn("lower than the published 200", out)
        self.assertEqual((self.current()["release"], self.current()["catalogSerial"]), ("1.0.1-1", 200))

    def test_db_naming_an_older_package_is_refused(self):
        self.release("1.0.1-1", {"grassfield-desktop": "1.0.1-1", "grassfield-icons": "1.0.1-1"})
        self.run_once()
        self.release("1.0.2-1", {"grassfield-desktop": "1.0.2-1", "grassfield-icons": "1.0.0-1"})
        with self.assertRaises(publish.Refused) as e:
            self.run_once(now=1793099999)
        self.assertIn("grassfield-icons 1.0.0-1, older than the published 1.0.1-1", str(e.exception))

    def test_a_catalog_alone_is_never_the_first_snapshot(self):
        with self.assertRaises(publish.Refused):
            self.run_once(self.catalog(100))
        self.assertEqual(self.store.read_pointer(), (None, None))

    def test_latest_state_after_a_cancelled_run(self):
        # A release run was cancelled while waiting; the next run, started by a catalog change, publishes both.
        self.release("1.0.0-1")
        self.run_once()
        self.release("1.0.1-1")
        self.run_once(self.catalog(300), now=1793099999)
        m = self.current()
        self.assertEqual((m["release"], m["catalogSerial"]), ("1.0.1-1", 300))

    def test_pointer_moved_while_building(self):
        self.release("1.0.0-1")
        first, _ = self.run_once()
        store, moved = self.store, []
        original = store.put_snapshot

        def put_and_move(snapshot, files):
            original(snapshot, files)
            if not moved:  # someone else moves the pointer once, after this run read it
                moved.append(snapshot)
                other = "20261027T000000Z-other"
                original(other, {"manifest.json": store.snapshot_path(first, "manifest.json"),
                                 **{n: store.snapshot_path(first, n) for n in store.manifest(first)["files"]}})
                self.assertTrue(store.write_pointer_if(store.read_pointer()[1], other))
        store.put_snapshot = put_and_move
        snapshot, out = self.run_once(self.catalog(100), now=1793099999)
        self.assertIn("the pointer moved", out)
        self.assertFalse(os.path.exists(os.path.join(store.base, "snap", moved[0])))  # the stale snapshot is dropped
        self.assertEqual(store.read_pointer()[0], snapshot)
        self.assertEqual((self.current()["catalogSerial"], self.current()["previous"]), (100, "20261027T000000Z-other"))

    def test_immutable_names(self):
        self.release("1.0.0-1")
        self.run_once()
        self.release("1.0.1-1")
        with open(os.path.join(self.releases, "1.0.1-1", "grassfield-desktop-1.0.0-1-x86_64.pkg.tar.zst"), "w") as f:
            f.write("other bytes under a published name\n")
        with self.assertRaises(publish.Refused) as e:
            self.run_once(now=1793099999)
        self.assertIn("already published with other content", str(e.exception))

    def test_prune_keeps_the_current_snapshot(self):
        self.release("1.0.0-1")
        old, _ = self.run_once()
        self.release("1.0.1-1")
        new, _ = self.run_once(now=1793099999)
        for s in (old, new):
            os.utime(os.path.join(self.store.base, "snap", s), (0, 0))
        publish.prune(self.store, 7, now=1793095200 + 30 * 86400)
        self.assertEqual([s for s, _ in self.store.snapshots()], [new])


if __name__ == "__main__":
    unittest.main()
