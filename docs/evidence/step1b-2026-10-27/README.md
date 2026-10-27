# Step 1b evidence (2026-10-27)
Every run below is on this repository's commit **7744988**: its scripts, tools and tests, extracted with `git archive` into
a clean folder. The commit after it changes this folder, README and STATE only. Docker 29.9.2, image
`archlinux:base@sha256:52dfbd5afb23a220d5ee92dafcb4c788d96c026ed04179890c23adef4c897fa0`. Every key is a throwaway one,
made inside the container of its run and gone with it. Each test counts its own checks ("done: N checks, M failure(s)").

**grassfield used:** main at **ae121e8** (the merge of grassfield #16, the step 1 client). The tags these runs build are
local commits in scratch clones, never pushed:
- `tests/e2e.sh` makes them inside its container: v1.0.0, v1.0.1 and v1.1.0-beta1 on ae121e8, each with its notes and a
  `repository.conf` that pins the run's key K on a `file://` base;
- `ci-path.sh` uses a clone of ae121e8 with v1.0.0-rc1 (3122062: its release notes) and v1.0.0-rc2 (5ac44f9: VERSION and
  notes).

| File | Command | Result |
|---|---|---|
| `unit-tests-output.txt` | `tests/run-in-container.sh --network host` (the catalog's and the publisher's unit tests) | exit 0, `Ran 52 tests … OK`, nothing skipped |
| `release-build-output.txt` | `tests/release-build.sh` | exit 0, "done: 33 checks, 0 failure(s)" |
| `e2e-output.txt` | `tests/e2e.sh --grassfield <clone of grassfield> --ref <ae121e8>` | running at this commit; recorded with the next |
| `ci-path-output.txt` | `ci-path.sh` (here) in one container, with `keyring/` as it will be after O11 (a throwaway project key KP in it) | running at this commit; recorded with the next |
| `ci-smoke-rc1.txt`, `ci-smoke-rc2.txt` | `build.yml`'s test job (`tests/smoke.sh`) on each build `ci-path.sh` made | after ci-path.sh; recorded with the next |
| `gitleaks-output.txt` | gitleaks v8.18.4 on `origin/main..HEAD` and on the tree | exit 0 and exit 0, "no leaks found" |

What `ci-path.sh` runs:
- two tags, each built in a fresh tree with `build.yml`'s build-step commands and a throwaway build key;
- for each, `build.yml`'s release job:
  - `sign-release.sh prepare`, without the key;
  - `sign-release.sh sign`, with KP and gpg only;
  - `check-tree.sh --trusted --keyring-src`, without the key;
- then `tools/publish.py`;
- then a client that installs rc1 and updates to rc2;
- the counter-case: rc2 signed without the published keyring, which the publisher refuses.

This client's build has an https base (main's `repository.conf`), so it fetches notes over https only and gets none
from the `file://` view. `e2e.sh` verifies notes end to end.

Not run: the workflows on GitHub (no deploy key exists, nothing may be published); a conditional write on real storage
(the host is not chosen, O8).
