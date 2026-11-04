"""tools/catalog.py sign with a passphrase-protected key (the owner's key has one; publish.yml gives it in
GRASSFIELD_SIGNING_PASSPHRASE). Runs only in the test container (throwaway keys, CLAUDE.md).

NOT VERIFIED where it was written: docker was denied there, so this test has not run; the container run of
tests/run-in-container.sh (CI's catalog.yml) is its first execution.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import catalog  # noqa: E402
import test_catalog  # noqa: E402

HAVE_TOOLS = test_catalog.IN_CONTAINER and shutil.which("gpg") is not None
PASSPHRASE = "correct horse battery staple"


@unittest.skipUnless(HAVE_TOOLS, "needs GnuPG in the test container (tests/run-in-container.sh)")
class SignWithPassphrase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp()
        env = catalog.child_env(cls.home)
        subprocess.run(["gpg", "--batch", "--pinentry-mode", "loopback", "--passphrase", PASSPHRASE, "--quick-gen-key",
                        "Grassfield passphrase test <pp@grassfield.invalid>", "ed25519", "sign", "1d"],
                       check=True, env=env, capture_output=True)
        out = subprocess.run(["gpg", "--batch", "--with-colons", "--list-keys"], check=True, env=env,
                             capture_output=True, text=True).stdout
        cls.key = next(line.split(":")[9] for line in out.splitlines() if line.startswith("fpr:"))

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["gpgconf", "--kill", "all"], env=catalog.child_env(cls.home), check=False)
        shutil.rmtree(cls.home)

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.path = os.path.join(self.dir, "grassfield-catalog.v1.json")
        with open(self.path, "w") as f:
            f.write("{}\n")

    def test_signs_with_the_passphrase_from_the_environment(self):
        with unittest.mock.patch.dict(os.environ, {"GRASSFIELD_SIGNING_PASSPHRASE": PASSPHRASE}):
            sig = catalog.sign(self.path, self.home, self.key)
        out = subprocess.run(["gpg", "--batch", "--verify", sig, self.path], env=catalog.child_env(self.home),
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_fails_closed_without_or_with_a_wrong_passphrase(self):
        for value in (None, "wrong"):
            # no cached passphrase from an earlier use of the key
            subprocess.run(["gpgconf", "--kill", "gpg-agent"], env=catalog.child_env(self.home), check=False)
            env = {k: v for k, v in os.environ.items() if k != "GRASSFIELD_SIGNING_PASSPHRASE"}
            if value:
                env["GRASSFIELD_SIGNING_PASSPHRASE"] = value
            with unittest.mock.patch.dict(os.environ, env, clear=True):
                with self.assertRaises(subprocess.CalledProcessError):
                    catalog.sign(self.path, self.home, self.key)
            self.assertFalse(os.path.exists(self.path + ".sig"))


if __name__ == "__main__":
    unittest.main()
