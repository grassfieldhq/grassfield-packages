"""Static checks over the workflows: no cache can be restored or saved by a run that can reach the release job, the
release job receives the tested artifact only, the artifact holds regular files only, and a tag is built only if it is on
grassfield's main.

actions/cache unpacks an entry with tar -P into the runner's workspace: it can write anywhere there, and nothing checks
it. So a run of main (which can reach the release job, and with it the project's signing key) must restore nothing.
The one switch is the job env USE_CACHE of build.yml, defined there and nowhere else; every step that caches (actions/cache,
or any action whose name says cache, or any known caching action or input) must be guarded by it, and no other workflow
may cache at all (docs/build-caches.md).

Each guard is a function of the parsed YAML that returns its problems; the tests run it on the real files (no problem) and
on in-memory mutations of them (a problem each), so that a guard that stops guarding is itself caught.
"""

import copy
import os
import pathlib
import re
import unittest

try:
    import yaml
except ImportError:  # the container image of tests/run-in-container.sh has no PyYAML
    yaml = None

WORKFLOWS = pathlib.Path(__file__).resolve().parent.parent / ".github" / "workflows"
SWITCH = "${{ github.ref != 'refs/heads/main' && startsWith(github.ref, 'refs/heads/') }}"
GATE = "env.USE_CACHE == 'true'"
RELEASE_IF = "github.ref == 'refs/heads/main' && startsWith(inputs.ref, 'v')"
INPUT = "${{ inputs.ref }}"
# Actions that cache without "cache" in their name, or by an input.
KNOWN_CACHING_ACTIONS = (
    "gradle/actions/setup-gradle", "gradle/gradle-build-action", "docker/build-push-action", "docker/bake-action",
    "astral-sh/setup-uv", "ruby/setup-ruby", "actions/setup-node", "actions/setup-python", "actions/setup-go",
    "actions/setup-java", "actions/setup-dotnet", "pnpm/action-setup", "oven-sh/setup-bun", "mozilla-actions/sccache-action",
    "hendrikmuhs/ccache-action", "docker/setup-buildx-action", "useblacksmith/", "runs-on/",
)
CACHING_INPUTS = ("cache-from", "cache-to", "enable-cache", "bundler-cache", "cache-dependency-path", "cache-read-only")


def evaluate(expression, ref):
    """Evaluate a workflow expression made of github.ref, string literals, !=, ==, && and startsWith(), for a github.ref."""
    m = re.fullmatch(r"\s*\$\{\{(.*)\}\}\s*", expression, re.S)
    py = (m.group(1) if m else expression).strip()
    if not re.fullmatch(r"[\w\s.'/&!=,()\-]*", py) or not set(re.findall(r"[A-Za-z_]\w*", re.sub(r"'[^']*'", "", py))) <= {
        "github", "ref", "startsWith"
    }:
        raise ValueError(f"unsupported expression: {expression}")
    py = re.sub(r"startsWith\(\s*([^,()]+?)\s*,\s*([^()]+?)\s*\)", r"(\1).startswith(\2)", py)
    py = py.replace("&&", " and ").replace("github.ref", "ref")
    return bool(eval(py, {"__builtins__": {}}, {"ref": ref}))  # noqa: S307 (a vetted charset, our own file)


def use_cache(doc, ref):
    """The real switch of the parsed build.yml, evaluated for a github.ref."""
    return evaluate(doc["jobs"]["build"]["env"]["USE_CACHE"], ref)


def load(path):
    return yaml.safe_load(path.read_text())


def load_all():
    return {path.name: load(path) for path in sorted(WORKFLOWS.glob("*.yml"))}


def steps_of(doc):
    for name, job in doc.get("jobs", {}).items():
        for i, step in enumerate(job.get("steps", [])):
            yield name, i, step


def as_list(needs):
    return [needs] if isinstance(needs, str) else list(needs or [])


def caches_something(step):
    uses = str(step.get("uses", "")).split("@")[0].lower()
    with_ = {str(k).lower() for k in (step.get("with") or {})}
    return (
        "cache" in uses
        or any(uses.startswith(a.lower()) for a in KNOWN_CACHING_ACTIONS)
        or any("cache" in k for k in with_)
        or bool(with_ & set(CACHING_INPUTS))
    )


def cache_problems(docs):
    out = []
    for fname, doc in docs.items():
        for job, i, step in steps_of(doc):
            if not caches_something(step):
                continue
            where = f"{fname}: {job}: {step.get('name', step.get('uses', i))}"
            if fname != "build.yml" or job != "build":
                out.append(f"{where}: a cache step outside the build job of build.yml")
                continue
            cond = str(step.get("if", ""))
            if "||" in cond:
                out.append(f"{where}: an `or` could bypass the switch")
            if GATE not in [c.strip() for c in cond.split("&&")]:
                out.append(f"{where}: not behind {GATE}")
    return out


def switch_problems(docs):
    """The switch is defined once, in the build job's env; nothing else sets, overrides or exports it."""
    out = []
    build = docs["build.yml"]["jobs"]["build"]
    if build.get("env", {}).get("USE_CACHE") != SWITCH:
        out.append("the build job's USE_CACHE is not the expected expression")
    for fname, doc in docs.items():
        if "USE_CACHE" in (doc.get("env") or {}):
            out.append(f"{fname}: USE_CACHE in the workflow env")
        for jname, job in doc.get("jobs", {}).items():
            if "USE_CACHE" in (job.get("env") or {}) and (fname, jname) != ("build.yml", "build"):
                out.append(f"{fname}: job {jname} defines USE_CACHE")
        for job, i, step in steps_of(doc):
            if "USE_CACHE" in (step.get("env") or {}):
                out.append(f"{fname}: {job} step {i} overrides USE_CACHE in its env")
            for line in str(step.get("run", "")).splitlines():
                if "USE_CACHE" not in line:
                    continue
                if re.search(r"GITHUB_(ENV|OUTPUT|STATE)", line) or re.match(r"\s*USE_CACHE\s*=", line):
                    out.append(f"{fname}: {job} step {i} writes USE_CACHE: {line.strip()}")
            if re.search(r"(?i)\bUSE_CACHE\b", str(step.get("with", ""))) and "script" in (step.get("with") or {}):
                out.append(f"{fname}: {job} step {i} script names USE_CACHE")
    # Any evaluation of the real expression: only a branch other than main may switch it on.
    for ref, expected in CASES:
        if evaluate(build.get("env", {}).get("USE_CACHE", "${{ true }}"), ref) != expected:
            out.append(f"the switch answers wrongly for {ref}")
    return out


CASES = [
    ("refs/heads/main", False),
    ("refs/tags/v1.0.0", False),
    ("refs/pull/1/merge", False),
    ("refs/heads/feat/faster-builds", True),
]


def release_problems(doc):
    out = []
    jobs = doc["jobs"]
    release, test, build = jobs["release"], jobs["test"], jobs["build"]
    if release.get("if") != RELEASE_IF:
        out.append("the release job's condition changed")
    if as_list(release.get("needs")) != ["test"]:
        out.append(f"the release job needs {as_list(release.get('needs'))}, not exactly ['test']")
    if as_list(test.get("needs")) != ["build"]:
        out.append(f"the test job needs {as_list(test.get('needs'))}, not exactly ['build']")

    def downloads(job):
        return [s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/download-artifact")]

    def uploads(job):
        return [s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact")]

    tested = [s.get("with", {}).get("name") for s in downloads(test)]
    got = [s.get("with", {}).get("name") for s in downloads(release)]
    made = [s.get("with", {}).get("name") for s in uploads(build)]
    if len(tested) != 1 or len(set(made)) != 1 or tested != made:
        out.append(f"the test job does not download the one artifact the build job uploads ({tested} vs {made})")
    if got != tested:
        out.append(f"the release job downloads {got}, not exactly the tested artifact {tested}")
    for s in release["steps"]:
        w = s.get("with") or {}
        if str(s.get("uses", "")).startswith("actions/download-artifact") and ("pattern" in w or "run-id" in w or "github-token" in w):
            out.append("the release job's download names a pattern or another run")
    if any(uploads(release)) or any(str(s.get("uses", "")).startswith("actions/checkout") and (s.get("with") or {}).get("repository")
                                    for s in release["steps"]):
        out.append("the release job uploads an artifact or checks out another repository")
    return out


def artifact_problems(doc):
    """The build job's upload takes a folder of regular files only, made by a step that fails on any other entry."""
    out = []
    steps = doc["jobs"]["build"]["steps"]
    ups = [i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("actions/upload-artifact")]
    if len(ups) != 1:
        return [f"expected one upload step in the build job, found {len(ups)}"]
    up = steps[ups[0]]
    if str((up.get("with") or {}).get("path", "")).strip() != "${{ runner.temp }}/upload":
        out.append("the upload does not take the regular-files folder only")
    prep = [s for s in steps[: ups[0]] if "RUNNER_TEMP/upload" in str(s.get("run", ""))]
    if len(prep) != 1:
        return out + ["no single step makes the upload folder before the upload"]
    run, cond = str(prep[0].get("run", "")), str(prep[0].get("if", ""))
    if "! -type f ! -type d" not in run:
        out.append("the folder step does not look for non-regular entries")
    if not re.search(r"-type f\b.*-print0", run) or "tar " not in run:
        out.append("the folder step does not copy regular files only")
    if not re.search(r"if \[ -n \"\$bad\" \]; then.*?exit 1", run, re.S):
        out.append("the folder step does not fail on a non-regular entry")
    if not re.search(r"if \[ -L out \]; then[^\n]*exit 1", run):
        out.append("the folder step does not fail when out itself is a link")
    if re.search(r"\b(find|cp|rsync)\b[^\n|]*\s-[a-zA-Z]*[LH]\b|\btar\b[^\n|]*\s-[a-zA-Z]*h\b|--dereference|-follow", run):
        out.append("the folder step follows links")
    if cond != "always()" or prep[0].get("continue-on-error"):
        out.append("the folder step must always run and fail loudly")
    if up.get("if") != "always()":
        out.append("the upload must run even after the failure (for the diagnosis)")
    return out


def tag_problems(doc):
    """A run that can reach the release job refuses a commit that is not on grassfield's main, before it builds."""
    out = []
    steps = doc["jobs"]["build"]["steps"]
    docker = [i for i, s in enumerate(steps) if "docker run" in str(s.get("run", "")) and "build-channel.sh" in str(s.get("run", ""))]
    checkout = [i for i, s in enumerate(steps) if (s.get("with") or {}).get("repository") == "grassfieldhq/grassfield"]
    guard = [i for i, s in enumerate(steps) if "merge-base --is-ancestor" in str(s.get("run", ""))]
    if len(guard) != 1 or not docker or len(checkout) != 1:
        return ["the ancestry check, the grassfield checkout or the build step is missing"]
    g = steps[guard[0]]
    if not checkout[0] < guard[0] < docker[0]:
        out.append("the ancestry check is not between the grassfield checkout and the build")
    if g.get("if") != RELEASE_IF:
        out.append("the ancestry check does not run for exactly the runs that can reach the release job")
    if g.get("continue-on-error"):
        out.append("the ancestry check is allowed to fail")
    run = str(g.get("run", ""))
    if "refs/remotes/origin/main" not in run or "HEAD" not in run or "exit 1" not in run or "set -e" not in run:
        out.append("the ancestry check does not compare HEAD with origin/main and fail")
    if "--is-shallow-repository" not in run:
        out.append("the ancestry check does not refuse a shallow history")
    if (steps[checkout[0]].get("with") or {}).get("fetch-depth") != 0:
        out.append("the grassfield checkout is not a full fetch")
    # What is checked is what is built: the checkout, the check and the build all take the dispatch input, and the check
    # requires the checkout to be the tag's commit (a branch of the same name is checked out first).
    if (steps[checkout[0]].get("with") or {}).get("ref") != INPUT:
        out.append("the grassfield checkout does not take the dispatch input")
    if (g.get("env") or {}).get("INPUT_REF") != INPUT:
        out.append("the ancestry check does not read the dispatch input")
    if not re.search(r'refs/tags/\$INPUT_REF\^\{commit\}', run) or 'git rev-parse HEAD' not in run:
        out.append("the ancestry check does not require the checkout to be the tag's commit")
    build = steps[docker[0]]
    if (build.get("env") or {}).get("REF") != INPUT or '--ref "$REF"' not in str(build.get("run", "")):
        out.append("the build step does not build the dispatch input")
    return out


def action_problems(docs):
    """No local or container action anywhere, and the build workflow downloads only artifacts of its own run."""
    out = []
    for name, doc in docs.items():
        for job, _, s in steps_of(doc):
            uses = str(s.get("uses", ""))
            if uses.startswith("./") or uses.startswith("docker://"):
                out.append(f"{name} {job}: a local or container action ({uses})")
            w = s.get("with") or {}
            if name == "build.yml" and uses.startswith("actions/download-artifact") and \
                    ("run-id" in w or "github-token" in w or "repository" in w):
                out.append(f"build.yml {job}: a download from another run or repository")
    return out


def mutated(fn):
    """A deep copy of every workflow, changed in place by fn(docs)."""
    docs = copy.deepcopy(load_all())
    fn(docs)
    return docs


def insert_before(job, marker_id, step):
    def go(docs):
        steps = docs["build.yml"]["jobs"][job]["steps"]
        idx = next(i for i, s in enumerate(steps) if s.get("id") == marker_id)
        steps.insert(idx, step)
    return go


class Guards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # In CI a missing PyYAML must not silently disable the guard: it fails. Locally it skips.
        if yaml is None:
            if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
                raise AssertionError("PyYAML is missing in CI: the guards did not run (install python-yaml)")
            raise unittest.SkipTest("PyYAML is not installed")
        cls.docs = load_all()


class TheRealWorkflows(Guards):
    def test_the_switch_is_evaluated_for_real(self):
        build = self.docs["build.yml"]
        self.assertEqual(switch_problems(self.docs), [])
        for ref, expected in CASES:
            self.assertEqual(use_cache(build, ref), expected, ref)

    def test_the_evaluator_is_not_a_tautology(self):
        self.assertTrue(evaluate("${{ github.ref != 'refs/heads/main' }}", "refs/tags/v1"))
        self.assertFalse(evaluate("${{ github.ref != 'refs/heads/main' }}", "refs/heads/main"))
        self.assertFalse(evaluate("${{ startsWith(github.ref, 'refs/heads/') }}", "refs/pull/1/merge"))
        with self.assertRaises(ValueError):
            evaluate("${{ __import__('os') }}", "x")

    def test_every_cache_step_is_behind_the_switch(self):
        self.assertEqual(cache_problems(self.docs), [])
        found = [s for _, _, s in steps_of(self.docs["build.yml"]) if caches_something(s)]
        self.assertGreaterEqual(len(found), 6, "the restore and save steps are expected: this check must not pass empty")

    def test_the_steps_that_feed_a_restore_are_behind_the_switch(self):
        ids = {s["id"]: s for _, _, s in steps_of(self.docs["build.yml"]) if "id" in s}
        for key in ("mode", "pacman-cache", "ccache", "data", "after"):
            self.assertIn(GATE, str(ids[key].get("if", "")), key)

    def test_the_release_job(self):
        self.assertEqual(release_problems(self.docs["build.yml"]), [])
        self.assertEqual(as_list(self.docs["build.yml"]["jobs"]["release"]["needs"]), ["test"])
        for step in self.docs["build.yml"]["jobs"]["release"]["steps"]:
            self.assertFalse(caches_something(step), step.get("name"))
        # A release-capable run (main, a `v*` input) has the switch off: no restore can run in it.
        self.assertFalse(use_cache(self.docs["build.yml"], "refs/heads/main"))

    def test_no_other_workflow_uses_a_cache(self):
        for name, doc in self.docs.items():
            if name != "build.yml":
                self.assertEqual([p for p in cache_problems({name: doc})], [], name)

    def test_the_artifact_is_regular_files_only(self):
        self.assertEqual(artifact_problems(self.docs["build.yml"]), [])

    def test_a_tag_must_be_on_main(self):
        self.assertEqual(tag_problems(self.docs["build.yml"]), [])

    def test_no_local_action_and_no_download_from_another_run(self):
        self.assertEqual(action_problems(self.docs), [])

    def test_every_action_is_pinned_by_sha(self):
        for path in sorted(WORKFLOWS.glob("*.yml")):
            for line in path.read_text().splitlines():
                if re.search(r"uses:\s*\S+@", line):
                    self.assertRegex(line, r"@[0-9a-f]{40}( |$)", f"{path.name}: {line.strip()}")


class MutationsAreCaught(Guards):
    """Each gap the reviewer found, and the obvious variants, must make its guard fail."""

    def caught(self, guard, docs, key=None):
        problems = guard(docs if key is None else docs[key])
        self.assertTrue(problems, "the mutation passed the guard")
        return problems

    def test_a_third_party_cache_action_in_the_release_job(self):
        for action in ("hendrikmuhs/ccache-action", "Swatinem/Rust-Cache", "buildjet/cache", "mozilla-actions/sccache-action"):
            def go(d, action=action):
                d["build.yml"]["jobs"]["release"]["steps"].insert(0, {"uses": f"{action}@" + "0" * 40})
            self.caught(cache_problems, mutated(go))

    def test_a_third_party_cache_action_in_the_build_job_without_the_gate(self):
        def go(d):
            d["build.yml"]["jobs"]["build"]["steps"].insert(3, {"uses": "hendrikmuhs/ccache-action@" + "0" * 40})
        self.caught(cache_problems, mutated(go))

    def test_a_cache_input_on_another_action_or_in_another_workflow(self):
        def go(d):
            d["build.yml"]["jobs"]["release"]["steps"].insert(0, {"uses": "actions/setup-python@" + "0" * 40, "with": {"cache": "pip"}})
        self.caught(cache_problems, mutated(go))

        def other(d):
            d["poll.yml"]["jobs"][next(iter(d["poll.yml"]["jobs"]))]["steps"].insert(0, {"uses": "foo/bar-cache@" + "0" * 40})
        self.caught(cache_problems, mutated(other))

    def test_a_gate_with_an_or_or_without_the_switch(self):
        def go(d):
            s = next(s for s in d["build.yml"]["jobs"]["build"]["steps"] if s.get("id") == "ccache")
            s["if"] = "env.USE_CACHE == 'true' || always()"
        self.caught(cache_problems, mutated(go))

        def go2(d):
            s = next(s for s in d["build.yml"]["jobs"]["build"]["steps"] if s.get("id") == "ccache")
            del s["if"]
        self.caught(cache_problems, mutated(go2))

    def test_a_step_writes_the_switch_to_the_environment_before_the_restores(self):
        for run in (
            'echo "USE_CACHE=true" >> "$GITHUB_ENV"',
            "echo USE_CACHE=true >>$GITHUB_ENV",
            'echo "USE_CACHE=true" >> "$GITHUB_OUTPUT"',
            'x=true; echo "USE_CACHE=$x" | tee -a "$GITHUB_ENV"',
            "cat >>\"$GITHUB_ENV\" <<EOF\nUSE_CACHE=true\nEOF",
        ):
            go = insert_before("build", "mode", {"name": "sneaky", "run": run})
            self.caught(switch_problems, mutated(go))

    def test_the_switch_is_defined_elsewhere_or_changed(self):
        def step_env(d):
            d["build.yml"]["jobs"]["build"]["steps"][0]["env"] = {"USE_CACHE": "true"}
        self.caught(switch_problems, mutated(step_env))

        def wf_env(d):
            d["build.yml"]["env"]["USE_CACHE"] = "true"
        self.caught(switch_problems, mutated(wf_env))

        def other_job(d):
            d["build.yml"]["jobs"]["release"]["env"]["USE_CACHE"] = "true"
        self.caught(switch_problems, mutated(other_job))

        def weaker(d):
            d["build.yml"]["jobs"]["build"]["env"]["USE_CACHE"] = "${{ github.ref != 'refs/heads/main' }}"
        self.caught(switch_problems, mutated(weaker))

    def test_the_release_job_needs_more_or_less_than_the_test_job(self):
        for needs in (["test", "build"], "build", [], ["build", "test"], ["test", "extra"]):
            def go(d, needs=needs):
                d["build.yml"]["jobs"]["release"]["needs"] = needs
            self.caught(release_problems, mutated(go), "build.yml")

    def test_the_release_job_downloads_something_else(self):
        def other_name(d):
            for s in d["build.yml"]["jobs"]["release"]["steps"]:
                if str(s.get("uses", "")).startswith("actions/download-artifact"):
                    s["with"]["name"] = "another-artifact"
        self.caught(release_problems, mutated(other_name), "build.yml")

        def extra(d):
            d["build.yml"]["jobs"]["release"]["steps"].append(
                {"uses": "actions/download-artifact@" + "0" * 40, "with": {"name": "grassfield-channel-${{ github.run_id }}", "path": "x"}})
        self.caught(release_problems, mutated(extra), "build.yml")

        def pattern(d):
            for s in d["build.yml"]["jobs"]["release"]["steps"]:
                if str(s.get("uses", "")).startswith("actions/download-artifact"):
                    s["with"]["pattern"] = "*"
        self.caught(release_problems, mutated(pattern), "build.yml")

    def test_the_artifact_follows_links_or_is_not_checked(self):
        def raw(d):
            for s in d["build.yml"]["jobs"]["build"]["steps"]:
                if str(s.get("uses", "")).startswith("actions/upload-artifact"):
                    s["with"]["path"] = "out"
        self.caught(artifact_problems, mutated(raw), "build.yml")

        def no_fail(d):
            for s in d["build.yml"]["jobs"]["build"]["steps"]:
                if s.get("id") == "upload-folder":
                    s["run"] = s["run"].replace("exit 1", "true")
        self.caught(artifact_problems, mutated(no_fail), "build.yml")

        def dropped(d):
            steps = d["build.yml"]["jobs"]["build"]["steps"]
            steps[:] = [s for s in steps if s.get("id") != "upload-folder"]
        self.caught(artifact_problems, mutated(dropped), "build.yml")

        def deref(d):
            for s in d["build.yml"]["jobs"]["build"]["steps"]:
                if s.get("id") == "upload-folder":
                    s["run"] = s["run"].replace("find . -type f", "find -L . -type f").replace("tar -C", "tar -h -C")
        self.caught(artifact_problems, mutated(deref), "build.yml")

        def soft(d):
            for s in d["build.yml"]["jobs"]["build"]["steps"]:
                if s.get("id") == "upload-folder":
                    s["continue-on-error"] = True
        self.caught(artifact_problems, mutated(soft), "build.yml")

    def test_the_tag_check_is_removed_weakened_or_moved(self):
        def steps(d):
            return d["build.yml"]["jobs"]["build"]["steps"]

        def find(d):
            return next(s for s in steps(d) if "merge-base" in str(s.get("run", "")))

        def removed(d):
            steps(d).remove(find(d))
        self.caught(tag_problems, mutated(removed), "build.yml")

        def no_if(d):
            find(d)["if"] = "github.ref == 'refs/heads/main'"
        self.caught(tag_problems, mutated(no_if), "build.yml")

        def soft(d):
            find(d)["continue-on-error"] = True
        self.caught(tag_problems, mutated(soft), "build.yml")

        def moved(d):
            s = steps(d)
            g = find(d)
            s.remove(g)
            s.insert(next(i for i, x in enumerate(s) if "docker run" in str(x.get("run", "")) and "build-channel.sh" in str(x.get("run", ""))) + 1, g)
        self.caught(tag_problems, mutated(moved), "build.yml")

        def shallow(d):
            for s in steps(d):
                if (s.get("with") or {}).get("repository") == "grassfieldhq/grassfield":
                    s["with"]["fetch-depth"] = 1
        self.caught(tag_problems, mutated(shallow), "build.yml")

        def checkout_main(d):
            for s in steps(d):
                if (s.get("with") or {}).get("repository") == "grassfieldhq/grassfield":
                    s["with"]["ref"] = "main"
        self.caught(tag_problems, mutated(checkout_main), "build.yml")

        def build_other(d):
            for s in steps(d):
                if "docker run" in str(s.get("run", "")) and "build-channel.sh" in str(s.get("run", "")):
                    s["env"]["REF"] = "${{ inputs.ref }}-evil"
        self.caught(tag_problems, mutated(build_other), "build.yml")

        def any_commit(d):
            g = find(d)
            g["run"] = "\n".join(l for l in g["run"].split("\n") if "refs/tags/" not in l and '"$tag"' not in l)
        self.caught(tag_problems, mutated(any_commit), "build.yml")

    def test_out_itself_a_link_is_refused(self):
        def gone(d):
            for s in d["build.yml"]["jobs"]["build"]["steps"]:
                if s.get("id") == "upload-folder":
                    s["run"] = "\n".join(l for l in s["run"].split("\n") if "-L out" not in l)
        self.caught(artifact_problems, mutated(gone), "build.yml")

    def test_a_local_action_or_a_download_from_another_run(self):
        def local(d):
            d["build.yml"]["jobs"]["build"]["steps"].insert(0, {"uses": "./.github/actions/x"})
        self.caught(action_problems, mutated(local))

        def container(d):
            d["poll.yml"]["jobs"][next(iter(d["poll.yml"]["jobs"]))]["steps"].insert(0, {"uses": "docker://alpine:3"})
        self.caught(action_problems, mutated(container))

        def other_run(d):
            d["build.yml"]["jobs"]["build"]["steps"].insert(0, {"uses": "actions/download-artifact@" + "0" * 40,
                                                                "with": {"name": "x", "run-id": "1", "github-token": "t"}})
        self.caught(action_problems, mutated(other_run))


@unittest.skipIf(yaml is None, "needs PyYAML")
class EveryWorkflowFileIsValid(unittest.TestCase):
    """Third review of PR #22, finding 4: a push of 2c70286 started no job ("workflow file issue"), so CI never ran the unit
    tests. Whatever the cause, every workflow file is checked here for what GitHub refuses at startup and a plain load does
    not: a key twice in one mapping (PyYAML keeps the last), a job without runs-on or uses, a step with neither run nor uses
    (or both), a duplicated step id, a needs naming no job, and a trigger section."""

    @staticmethod
    def strict_load(path):
        class Loader(yaml.SafeLoader):
            pass

        def mapping(loader, node, deep=False):
            seen = set()
            for key_node, _ in node.value:
                key = loader.construct_object(key_node, deep=deep)
                if key in seen:
                    raise yaml.constructor.ConstructorError(None, None, f"duplicate key {key!r}", key_node.start_mark)
                seen.add(key)
            return yaml.SafeLoader.construct_mapping(loader, node, deep)

        Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
        return yaml.load(path.read_text(), Loader)

    def test_each_file_loads_without_a_repeated_key_and_has_the_shape_github_needs(self):
        files = sorted(WORKFLOWS.glob("*.yml"))
        self.assertGreaterEqual(len(files), 5)
        for path in files:
            with self.subTest(path.name):
                doc = self.strict_load(path)
                self.assertIsInstance(doc, dict)
                self.assertTrue(doc.get("name"), "a workflow has a name")
                self.assertTrue(True in doc or "on" in doc, "the trigger section (`on:` loads as True)")
                jobs = doc["jobs"]
                self.assertTrue(jobs)
                for job_id, job in jobs.items():
                    self.assertTrue("runs-on" in job or "uses" in job, f"job {job_id} has no runs-on or uses")
                    for need in ([job["needs"]] if isinstance(job.get("needs"), str) else job.get("needs", [])):
                        self.assertIn(need, jobs, f"job {job_id} needs {need}, which is no job")
                    ids = [st["id"] for st in job.get("steps", []) if "id" in st]
                    self.assertEqual(len(ids), len(set(ids)), f"job {job_id} repeats a step id")
                    for st in job.get("steps", []):
                        self.assertTrue(("run" in st) != ("uses" in st), f"a step of {job_id} needs exactly one of run and uses: {st.get('name')}")


if __name__ == "__main__":
    unittest.main()
