"""scripts/build-summary.sh turns the build statistics into the job summary; the workflows parse (docs/build-caches.md)."""

import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "build-summary.sh"

LOG = """[+61s] ==> Making package: grassfield-desktop 1.0.0rc3-1
[+70s] ==> Installing missing dependencies...
[+200s] ==> Starting build()...
[+210s] -- Build files have been written to: /build/src/packaging/arch/src/compositor-build
[+500s] -- Build files have been written to: /build/src/packaging/arch/src/i18n-build
[+900s] ==> Starting check()...
[+950s] ==> Creating package "grassfield-desktop"...
[+1400s] ==> Finished making: grassfield-desktop 1.0.0rc3-1
"""


class BuildSummary(unittest.TestCase):
    def run_script(self, files):
        with tempfile.TemporaryDirectory() as d:
            for name, text in files.items():
                (pathlib.Path(d) / name).write_text(text)
            return subprocess.run(["bash", str(SCRIPT), d], capture_output=True, text=True, check=False)

    def test_phases_tools_and_ccache_rate(self):
        r = self.run_script({
            "steps.tsv": "0\tpackage set\n40\tmakepkg\n1500\tend\n",
            "build.log": LOG,
            "profile.txt": "1 bash ps\n6 cc1plus ninja\n11 cc1plus ninja\n16 python3\n21 pacman zstd\n",
            "ccache.raw": "direct_cache_hit\t30\npreprocessed_cache_hit\t10\ncache_miss\t60\n",
        })
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("| makepkg | 1460 |", r.stdout)
        self.assertIn("| Starting build()... | 700 |", r.stdout)
        self.assertIn("| i18n-build | 290 |", r.stdout)
        self.assertIn("| C++ compiler | 10 |", r.stdout)
        self.assertIn("hits 40, misses 60, hit rate 40.0%", r.stdout)

    def test_no_cacheable_call_and_empty_directory(self):
        r = self.run_script({"ccache.raw": "direct_cache_hit\t0\ncache_miss\t0\n"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no cacheable compile call", r.stdout)
        self.assertEqual(self.run_script({}).returncode, 0)

    def test_usage(self):
        r = subprocess.run(["bash", str(SCRIPT), "/nonexistent-dir"], capture_output=True, text=True, check=False)
        self.assertEqual(r.returncode, 2)


class Workflows(unittest.TestCase):
    def test_parse_and_pins(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML is not installed")
        for f in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
            doc = yaml.safe_load(f.read_text())
            self.assertIn("jobs", doc, f.name)
        text = (ROOT / ".github" / "workflows" / "build.yml").read_text()
        for line in text.splitlines():
            if "uses:" in line and "actions/cache" in line:
                self.assertRegex(line, r"@[0-9a-f]{40} # v", "an action is pinned by SHA")


if __name__ == "__main__":
    unittest.main()
