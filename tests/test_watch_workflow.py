"""The daily toolkit watch (.github/workflows/watch-hyprland.yml) stays what it was written to be: it runs on a schedule and by
hand only (never on a pull request), uses no secret, pins every action by its commit SHA, never caches, and may only start a
workflow and open an issue. Each guard is a function of the parsed YAML that returns its problems; the tests run it on the real
file (no problem) and on mutations of it (a problem each).
"""
import copy
import pathlib
import re
import unittest

try:
    import yaml
except ImportError:  # the container image of tests/run-in-container.sh may have no PyYAML
    yaml = None

FILE = pathlib.Path(__file__).resolve().parent.parent / ".github" / "workflows" / "watch-hyprland.yml"
SHA = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")


def problems(doc):
    out = []
    on = doc.get("on", doc.get(True))
    if set(on) - {"schedule", "workflow_dispatch"}:
        out.append(f"triggers beyond schedule and workflow_dispatch: {sorted(set(on) - {'schedule', 'workflow_dispatch'})}")
    if not on.get("schedule"):
        out.append("no schedule")
    if doc.get("permissions") != {"actions": "write", "contents": "read", "issues": "write"}:
        out.append(f"permissions are not exactly actions: write, contents: read, issues: write: {doc.get('permissions')}")
    text = FILE.read_text() if doc.get("_text") is None else doc["_text"]
    if re.search(r"\$\{\{\s*secrets\.", text):
        out.append("a secret is used")
    for job in doc["jobs"].values():
        if "permissions" in job:
            out.append("a job widens or narrows the permissions on its own")
        for step in job["steps"]:
            uses = step.get("uses")
            if uses and not SHA.match(uses):
                out.append(f"{uses} is not pinned by a commit SHA")
            if uses and ("cache" in uses.lower() or "cache" in " ".join(map(str, (step.get("with") or {})))):
                out.append(f"{uses} caches")
            if uses and uses.startswith("actions/checkout") and (step.get("with") or {}).get("persist-credentials") is not False:
                out.append("checkout keeps the token in the clone")
    return out


@unittest.skipIf(yaml is None, "needs PyYAML")
class WatchWorkflow(unittest.TestCase):
    def doc(self):
        return yaml.safe_load(FILE.read_text())

    def test_theRealFileIsClean(self):
        self.assertEqual(problems(self.doc()), [])

    def test_aPullRequestTriggerIsCaught(self):
        d = self.doc()
        d["on"] = {"pull_request": None, "schedule": [{"cron": "1 1 * * *"}]}
        self.assertTrue(problems(d))

    def test_anUnpinnedActionIsCaught(self):
        d = self.doc()
        d["jobs"]["watch"]["steps"][0]["uses"] = "actions/checkout@v4"
        self.assertTrue(problems(d))

    def test_aSecretIsCaught(self):
        d = self.doc()
        d["_text"] = FILE.read_text() + "\n# ${{ secrets.GRASSFIELD_SIGNING_KEY }}\n"
        self.assertTrue(problems(d))

    def test_widerPermissionsAreCaught(self):
        d = self.doc()
        d["permissions"] = dict(d["permissions"], contents="write")
        self.assertTrue(problems(d))

    def test_aCredentialKeepingCheckoutIsCaught(self):
        d = copy.deepcopy(self.doc())
        del d["jobs"]["watch"]["steps"][0]["with"]
        self.assertTrue(problems(d))

    def test_theRebuildIsOnlyAnInputOfTheBuildWorkflow(self):
        text = FILE.read_text()
        self.assertIn('gh workflow run build.yml --ref main -f ref="$ref" -f pkgrel="$pkgrel"', text)
        self.assertEqual(len(re.findall(r"gh workflow run", text)), 1)


if __name__ == "__main__":
    unittest.main()
