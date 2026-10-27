"""tools/publish.py: one serialized publisher per channel (grassfield ADR-0033 h.2 as amended by ADR-0037 g).

Needs pacman's vercmp and bsdtar, and signs catalogs with throwaway keys: runs only in the test container
(tests/run-in-container.sh; CLAUDE.md: test keys are made in a test container and removed with it).
"""
import copy
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import catalog  # noqa: E402
import publish  # noqa: E402
import test_catalog  # noqa: E402  its sources; a module import, so its tests are not collected twice

HAVE_TOOLS = test_catalog.IN_CONTAINER and all(shutil.which(t) for t in ("vercmp", "bsdtar", "gpg", "gpgv"))


def make_key(home, uid):
    env = catalog.child_env(home)
    subprocess.run(["gpg", "--batch", "--pinentry-mode", "loopback", "--passphrase", "", "--quick-gen-key", uid,
                    "ed25519", "sign", "1d"], check=True, env=env, capture_output=True)
    out = subprocess.run(["gpg", "--batch", "--with-colons", "--list-keys", uid], check=True, env=env,
                         capture_output=True, text=True).stdout
    return next(line.split(":")[9] for line in out.splitlines() if line.startswith("fpr:"))


def make_db(path, packages):
    """A pacman sync database with only the desc fields publish.py reads."""
    with tarfile.open(path, "w:gz") as tar:
        for name, version in packages.items():
            data = f"%NAME%\n{name}\n\n%VERSION%\n{version}\n\n".encode()
            info = tarfile.TarInfo(f"{name}-{version}/desc")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


@unittest.skipUnless(HAVE_TOOLS, "needs vercmp, bsdtar and GnuPG in the test container (tests/run-in-container.sh)")
class Publisher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp()
        cls.keys = [make_key(cls.home, f"Grassfield test {i} <test{i}@grassfield.invalid>") for i in (1, 2)]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.home)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.releases = os.path.join(self.tmp, "releases")
        self.store = publish.LocalStore(os.path.join(self.tmp, "bucket"), "stable", "x86_64")
        os.makedirs(self.releases)
        # The keyring the Store verifies with: both keys in grassfield.gpg, only the first trusted.
        self.keyring = os.path.join(self.tmp, "keyring")
        os.makedirs(self.keyring)
        exported = subprocess.run(["gpg", "--batch", "--export"] + self.keys, check=True,
                                  env=catalog.child_env(self.home), capture_output=True).stdout
        with open(os.path.join(self.keyring, "grassfield.gpg"), "wb") as f:
            f.write(exported)
        with open(os.path.join(self.keyring, "grassfield-trusted"), "w") as f:
            f.write(f"{self.keys[0]}:4:\n")

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

    def catalog(self, serial, row="Tools", channel="stable", key=0):
        """A catalog built by tools/catalog.py from test_catalog's sources (row: the title of its one row, to change its
        content) and signed by a throwaway key."""
        folder = os.path.join(self.tmp, f"catalog-{serial}-{row}-{channel}-{key}")
        if os.path.exists(folder):
            return folder
        src = test_catalog.Sources()
        src.setUp()
        self.addCleanup(src.tearDown)
        section = copy.deepcopy(dict(test_catalog.GOOD["sections"][0], order=10))
        section["blocks"][1]["title"] = {"en": row}
        src.write("sections/discover.json", section)
        p = catalog.Problems()
        path = catalog.build(src.src, channel, serial, folder, p)
        self.assertIsNotNone(path, p.items)
        catalog.sign(path, self.home, self.keys[key])
        return folder

    def run_once(self, catalog=None, now=1793095200):
        with redirect_stdout(io.StringIO()) as out:
            snapshot = publish.publish(self.store, self.releases, catalog, now=now, keyring_dir=self.keyring)
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
        # The same content rebuilt with a higher serial (another run on the same main): still nothing new.
        again, out = self.run_once(self.catalog(150), now=1793099999)
        self.assertIsNone(again)
        self.assertIn("nothing new", out)
        self.assertEqual(self.store.read_pointer()[0], first)
        # Changed content with a higher serial is published, and its content hash recorded.
        self.assertIsNotNone(self.run_once(self.catalog(160, row="Other tools"), now=1793099999)[0])
        m = self.current()
        self.assertEqual(m["catalogSerial"], 160)
        self.assertRegex(m["catalogContent"], "^[0-9a-f]{64}$")

    def test_never_backwards(self):
        self.release("1.0.1-1")
        self.run_once(self.catalog(200))
        # An older catalog (a run built from an older main) and an older build leave the published state as it is.
        shutil.rmtree(os.path.join(self.releases, "1.0.1-1"))
        self.release("1.0.0-1")
        snapshot, out = self.run_once(self.catalog(100, row="Older tools"), now=1793099999)
        self.assertIsNone(snapshot)
        self.assertIn("older than the published release", out)
        self.assertIn("not above the published 200", out)
        self.assertEqual((self.current()["release"], self.current()["catalogSerial"]), ("1.0.1-1", 200))

    def test_a_catalog_must_pass_the_stores_checks(self):
        self.release("1.0.0-1")
        first, _ = self.run_once()
        refused = {
            "beta": self.catalog(100, channel="beta"),       # built and signed for the other channel
            "untrusted": self.catalog(100, key=1),           # signed by a key grassfield-trusted does not list
        }
        fake = shutil.copytree(self.catalog(100), os.path.join(self.tmp, "fake-sig"))
        with open(os.path.join(fake, publish.CATALOG_FILE + ".sig"), "wb") as f:
            f.write(b"not a signature\n")
        refused["fake .sig"] = fake
        changed = shutil.copytree(self.catalog(100), os.path.join(self.tmp, "changed"))
        with open(os.path.join(changed, publish.CATALOG_FILE), "ab") as f:
            f.write(b" ")
        refused["changed after signing"] = changed
        for why, folder in refused.items():
            with self.subTest(why), self.assertRaises(publish.Refused) as e:
                self.run_once(folder, now=1793099999)
            self.assertIn("does not pass the Store's checks for stable", str(e.exception))
        self.assertEqual(self.store.read_pointer()[0], first)

    def test_only_the_icons_the_catalog_lists_are_uploaded(self):
        self.release("1.0.0-1")
        folder = self.catalog(100)
        listed = sorted(os.listdir(os.path.join(folder, "catalog")))
        stray = os.path.join(folder, "catalog", "f" * 64 + ".png")
        with open(stray, "wb") as f:
            f.write(b"not listed")
        self.run_once(folder)
        self.assertEqual(sorted(os.listdir(os.path.join(self.store.base, "catalog"))), listed)
        self.assertEqual(self.current()["icons"], listed)

    def test_the_command_needs_the_keyring_with_a_catalog(self):
        with redirect_stdout(io.StringIO()), unittest.mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            code = publish.main(["--store", self.tmp, "--channel", "stable", "--catalog", self.catalog(100)])
        self.assertEqual(code, 2)
        self.assertIn("--catalog needs --keyring-dir", err.getvalue())

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

    def test_deliberate_rollback(self):
        # ADR-0033 h.2: a new snapshot with the older databases and notes, the catalog kept; never the pointer moved back.
        self.release("1.0.0-1")
        first, _ = self.run_once()
        self.release("1.0.1-1")
        second, _ = self.run_once(self.catalog(100), now=1793095300)
        with redirect_stdout(io.StringIO()) as out:
            back = publish.rollback(self.store, first, now=1793095400)
        self.assertNotIn(back, (first, second))
        self.assertIn("rollback to " + first, out.getvalue())
        m = self.current()
        self.assertEqual((m["release"], m["previous"], m["rollbackOf"], m["catalogSerial"]), ("1.0.0-1", second, first, 100))
        self.assertIn(publish.CATALOG_FILE, m["files"])
        for name in publish.SNAPSHOT_FILES + tuple(n + ".sig" for n in publish.SNAPSHOT_FILES):
            with open(self.store.snapshot_path(first, name), "rb") as a, open(self.store.snapshot_path(back, name), "rb") as b:
                self.assertEqual(a.read(), b.read(), name)
        # The newer release build withdrawn (scripts/rollback.sh), the next run leaves the rollback in place.
        shutil.rmtree(os.path.join(self.releases, "1.0.1-1"))
        again, out = self.run_once(self.catalog(100), now=1793095500)
        self.assertIsNone(again)
        self.assertIn("nothing new", out)
        # A newer tag publishes as usual.
        self.release("1.0.2-1")
        self.assertIsNotNone(self.run_once(self.catalog(100), now=1793095600)[0])
        self.assertEqual(self.current()["release"], "1.0.2-1")

    def test_rollback_refusals(self):
        self.release("1.0.0-1")
        first, _ = self.run_once()
        self.release("1.0.1-1")
        second, _ = self.run_once(now=1793095300)
        for target, why in ((second, "not an older snapshot"), ("20991231T000000Z-000000000000", "no snapshot"),):
            with self.subTest(why), self.assertRaises(publish.Refused) as e:
                publish.rollback(self.store, target, now=1793095400)
            self.assertIn(why, str(e.exception))
        with redirect_stdout(io.StringIO()):
            back = publish.rollback(self.store, first, now=1793095400)
        with self.assertRaises(publish.Refused) as e:  # the newer snapshot is not older than the rollback
            publish.rollback(self.store, second, now=1793095500)
        self.assertIn("not older than the current", str(e.exception))
        self.assertEqual(self.store.read_pointer()[0], back)
        with redirect_stdout(io.StringIO()), unittest.mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            code = publish.main(["--store", self.tmp, "--channel", "stable", "--rollback-to", first,
                                 "--releases", self.releases])
        self.assertEqual(code, 2)
        self.assertIn("--rollback-to publishes an older snapshot again, nothing else", err.getvalue())

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
