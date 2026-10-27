# O22 follow-up evidence (2026-10-27)
grassfield ADR-0033 owner decision O22 (grassfield PR #24): grassfield-desktop depends on grassfield-keyring. This
repository's follow-up (integrator review of grassfield #24's 532fb8f): the release guard, the keyring's `pre_remove`
reading its last line, e2e and smoke installing the three packages only.

Every run is on this repository's commit **f678b7d** (its scripts, keyring and tests) or **db904b8** (f678b7d plus
`guard.sh`), extracted with `git archive` into a clean folder. The commits after it change this folder and STATE only.
Docker, image `archlinux:base@sha256:52dfbd5afb23a220d5ee92dafcb4c788d96c026ed04179890c23adef4c897fa0`. Every key is a
throwaway one, made inside the container of its run and gone with it. Each test counts its own checks.

**grassfield used:** `448a381`, PR #24's head with the review fixes (grassfield-desktop depends on grassfield-keyring);
`4b7aa31`, main before #24 (it does not). Scratch commits and tags are made on them inside the containers, never pushed.

| File | Command | Result |
|---|---|---|
| `unit-tests-output.txt` | `tests/run-in-container.sh --network host` (with this network's proxy and CA) | exit 0, `Ran 53 tests … OK`, nothing skipped |
| `release-build-output.txt` | `tests/release-build.sh` | exit 0, "done: 36 checks, 0 failure(s)": the keyring's version read from `keyring/PKGBUILD` (20261027-2), check-tree.sh's "grassfield-desktop depends on grassfield-keyring" on every set, its refusal of a desktop without it, `pre_remove` deleting both keys of a list whose last line has no newline |
| `install-repro-output.txt` | `install-repro.sh` (here; pure bash, `pacman-key` stubbed) | main `b0e8494`: one of the two keys deleted; this branch: both |
| `guard-output.txt` | `guard.sh` (here) in one container, BEFORE=`4b7aa31`, AFTER=`448a381` | exit 0, "done: 6 checks, 0 failure(s)": `build-channel.sh` refuses `4b7aa31` after makepkg ("grassfield-desktop does not depend on grassfield-keyring"), no release build written; builds `448a381`; check-tree.sh finds the dependency in both sets |
| `smoke-output.txt` | `tests/smoke.sh` on guard.sh's accepted tree, in its own container | exit 0, "smoke: 6 checks, 0 failure(s)": `pacman -S` of the three packages, grassfield-keyring 20261027-2 "Installed as a dependency for another package" |
| `e2e-output.txt` | `tests/e2e.sh --grassfield <clone> --ref 448a381` | exit 0, "done: 44 checks, 0 failure(s)": four real builds; the client names the three packages and gets the keyring as a dependency; the keyring reused once through `keyring-check.sh`; `pacman -Rn` takes the section and the key away; this repository's keyless keyring trusts nothing |
| `gitleaks-output.txt` | gitleaks v8.18.4 on `origin/main..HEAD` and on the tree | exit 0 and exit 0, "no leaks found" |

Not run: the workflows on GitHub (no deploy key exists, nothing may be published).
