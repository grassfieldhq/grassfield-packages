"""Static checks over the workflows: no cache can be restored or saved by a run that can reach the release job.

actions/cache unpacks an entry with tar -P into the runner's workspace: it can write anywhere there, and nothing checks
it. So a run of main (which can reach the release job, and with it the project's signing key) must restore nothing.
The one switch is the job env USE_CACHE of build.yml; every step that uses actions/cache must be guarded by it, and no
other workflow may use a cache at all (docs/build-caches.md).
"""

import pathlib
import re
import unittest

try:
    import yaml
except ImportError:  # the container image of tests/run-in-container.sh has no PyYAML
    yaml = None

WORKFLOWS = pathlib.Path(__file__).resolve().parent.parent / ".github" / "workflows"
SWITCH = "${{ github.ref != 'refs/heads/main' && startsWith(github.ref, 'refs/heads/') }}"


def use_cache(ref):
    """The switch's expression, evaluated for a github.ref (kept equal to SWITCH by test_the_switch)."""
    return ref != "refs/heads/main" and ref.startswith("refs/heads/")


def load(path):
    return yaml.safe_load(path.read_text())


def steps_of(doc):
    for name, job in doc.get("jobs", {}).items():
        for i, step in enumerate(job.get("steps", [])):
            yield name, i, step


def caches_something(step):
    uses = str(step.get("uses", ""))
    with_ = step.get("with") or {}
    return uses.startswith("actions/cache") or "cache" in with_ or "cache-dependency-path" in with_


@unittest.skipIf(yaml is None, "PyYAML is not installed")
class CacheNeverReachesARelease(unittest.TestCase):
    def test_the_switch(self):
        build = load(WORKFLOWS / "build.yml")["jobs"]["build"]
        self.assertEqual(build["env"]["USE_CACHE"], SWITCH)
        for ref, expected in [
            ("refs/heads/main", False),
            ("refs/tags/v1.0.0", False),
            ("refs/pull/1/merge", False),
            ("refs/heads/feat/faster-builds", True),
        ]:
            self.assertEqual(use_cache(ref), expected, ref)

    def test_every_cache_step_is_behind_the_switch(self):
        doc = load(WORKFLOWS / "build.yml")
        found = []
        for job, i, step in steps_of(doc):
            if not caches_something(step):
                continue
            found.append((job, step.get("name", i)))
            self.assertEqual(job, "build", f"a cache step in job {job}: only the build job of a branch may cache")
            cond = str(step.get("if", ""))
            self.assertNotIn("||", cond, f"{step.get('name')}: an `or` could bypass the switch")
            self.assertIn("env.USE_CACHE == 'true'", [c.strip() for c in cond.split("&&")], step.get("name"))
        self.assertGreaterEqual(len(found), 6, "the restore and save steps are expected: this check must not pass empty")

    def test_the_steps_that_feed_a_restore_are_behind_the_switch(self):
        doc = load(WORKFLOWS / "build.yml")
        ids = {s["id"]: s for _, _, s in steps_of(doc) if "id" in s}
        for key, step in ids.items():
            if key in ("mode", "pacman-cache", "ccache", "data", "after"):
                self.assertIn("env.USE_CACHE == 'true'", str(step.get("if", "")), key)

    def test_the_release_job_has_no_cache_and_needs_the_tested_artifact_only(self):
        doc = load(WORKFLOWS / "build.yml")
        release = doc["jobs"]["release"]
        self.assertEqual(release["if"], "github.ref == 'refs/heads/main' && startsWith(inputs.ref, 'v')")
        for step in release["steps"]:
            self.assertFalse(caches_something(step), step.get("name"))
        # A release-capable run (main, a `v*` input) has the switch off: no restore can run in it.
        self.assertFalse(use_cache("refs/heads/main"))

    def test_no_other_workflow_uses_a_cache(self):
        for path in sorted(WORKFLOWS.glob("*.yml")):
            if path.name == "build.yml":
                continue
            for job, i, step in steps_of(load(path)):
                self.assertFalse(caches_something(step), f"{path.name}: {job} step {i} uses a cache")

    def test_the_cache_action_is_pinned_by_sha(self):
        for path in sorted(WORKFLOWS.glob("*.yml")):
            for line in path.read_text().splitlines():
                if re.search(r"uses:\s*\S+@", line):
                    self.assertRegex(line, r"@[0-9a-f]{40}( |$)", f"{path.name}: {line.strip()}")


if __name__ == "__main__":
    unittest.main()
