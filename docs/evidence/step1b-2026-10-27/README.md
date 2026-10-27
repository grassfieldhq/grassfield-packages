# Step 1b evidence (2026-10-27)
Outputs of runs made in the cloud session of step 1b, Docker 29.9.2, image
`archlinux:base@sha256:52dfbd5afb23a220d5ee92dafcb4c788d96c026ed04179890c23adef4c897fa0`; throwaway keys made per run
inside the containers, gone with them.

| File | Command | Result |
|---|---|---|
| `e2e-output.txt` | `tests/e2e.sh --grassfield <grassfield checkout> --ref claude/software-update-step1` (grassfield's step 1 client, merged in grassfield #16; this repository at 3efd2ca's tests and scripts) | exit 0, 72 PASS, 0 FAIL |
| `ci-build-output.txt` | the inline script of `build.yml`'s build job, then `tests/smoke.sh` (the test job), on a local clone of grassfield b5df468 plus one local commit adding release notes for 1.0.0-rc1 (never pushed); the first attempt without that commit stopped as it must: `1.0.0-rc1.en.txt is missing` | build job exit 0 (check-tree 0 failures); this file's test job part ran before the smoke fix |
| `ci-smoke-output.txt` | `tests/smoke.sh` on that build's artifact after 3efd2ca (grassfield-keyring installed by name, O21) | exit 0, smoke: 0 failures |
