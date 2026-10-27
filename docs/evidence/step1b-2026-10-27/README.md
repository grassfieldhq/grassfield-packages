# Step 1b evidence (2026-10-27)
Runs made in the cloud session of step 1b, after the integrator's opus review of e373590, on this repository's commit
**3a6a138** (scripts and tests, extracted with `git archive`; the later commits change documentation only). Docker 29.9.2,
image `archlinux:base@sha256:52dfbd5afb23a220d5ee92dafcb4c788d96c026ed04179890c23adef4c897fa0`. Every key is a throwaway
one made inside the container of its run and gone with it.

**grassfield used:** main at **ae121e8** (the merge of grassfield #16, the step 1 client). The tags these runs build are
local commits in scratch clones, never pushed:
- `tests/e2e.sh` makes them inside its container: v1.0.0, v1.0.1 and v1.1.0-beta1 on ae121e8, each with its notes and a
  `repository.conf` pinning the run's key K;
- the CI path uses a clone of ae121e8 with v1.0.0-rc1 (3122062: its release notes) and v1.0.0-rc2 (5ac44f9: VERSION and
  notes).

| File | Command | Result |
|---|---|---|
| `e2e-output.txt` | `tests/e2e.sh --grassfield <clone of grassfield> --ref <ae121e8>` | PENDING: the run on 3a6a138 is in progress at this commit; this file still holds the earlier run (3efd2ca's tests, 72 PASS) and is replaced when it ends |
| `release-build-output.txt` | `tests/release-build.sh` | exit 0, 0 FAIL: 17 checks (58 PASS lines with check-tree's own) |
| `ci-build-rc1.txt`, `ci-build-rc2.txt` | `build.yml`'s build job: its inline script, verbatim, in a fresh tree, for v1.0.0-rc1 and v1.0.0-rc2 (rc2 built again at another time than rc1, so that its grassfield-keyring has other bytes) | exit 0 each, check-tree 0 failures (22 PASS each) |
| `ci-smoke-rc1.txt`, `ci-smoke-rc2.txt` | `build.yml`'s test job: `tests/smoke.sh` on each artifact | exit 0 each, 0 failures: 6 checks each (28 PASS lines with check-tree's own) |
| `publish-interface-output.txt` | `publish-interface.sh` (here) in a container, with Grassfield Store step 1's `tools/publish.py` and `tools/catalog.py` from grassfield-packages PR #2 at e05f23e (unmerged; sha256 af76216b… and ad83e922…). It signs each tested release build with a throwaway "project" key (`sign-release.sh --published`) and publishes it with `tools/publish.py`. The store is checked with `check-tree.sh` as it is. A client installs rc1 from it, sees rc2 and installs it | exit 0, 0 FAIL: 15 checks (39 PASS lines with check-tree's own) |

Not run: the workflows on GitHub (no deploy key exists, nothing may be published); a conditional write on real storage
(the host is not chosen, O8).
