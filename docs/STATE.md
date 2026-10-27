# Grassfield packages — Current State
Last updated: 2026-10-27

## Done
- Repository created (private) with README, LICENSE (MIT), CLAUDE.md and this file.
- 2026-10-27 (cloud session, branch claude/pensive-thompson-fhk5um, owner brief "Grassfield Store", step 0, docs only): the
  repository's second role, the Store catalog Grassfield edits, added to README.md and CLAUDE.md. Its contract is grassfield
  ADR-0037 (Proposed, grassfieldhq/grassfield PR #15; this repository's PR #1): `grassfield-catalog.v1.json` + `.sig` + `catalog/<sha256>.png` in each
  channel's snapshot beside the repository, signed with the repository's key, verified by the Store like the release notes
  (ADR-0033 d.8). No code here before the opus PASS of ADR-0037.
- 2026-10-27, after the first opus review (FAIL, 3 MAJOR, in grassfield PR #15): the publication of both repositories' files
  is one serialized publisher per channel, building from the current snapshot, never backwards, with a conditional pointer
  write (MAJOR 3; ADR-0033 h.2 amended in grassfield PR #15); publishers' icons for apps without metadata (owner, ST10) with
  their licence and origin, needs legal review; CI refuses recipes that sync. README and CLAUDE.md updated.
- 2026-10-27, after the opus counter-review (FAIL, 1 MAJOR on grassfield's side, in grassfield PR #15): each publishing run
  publishes the latest state (the newest release built for the channel, the catalog of `main`'s head), since GitHub cancels
  a waiting run in a concurrency group when a newer one queues and each tag is built once; CI also refuses a `repo` app whose
  package owns no application entry (ADR-0037 SD1). README and CLAUDE.md updated. The owner's working rule of 2026-10-27
  (decisions taken in the session under "macOS first, no technical step for the user", recorded in ADR-0037 as SD rows;
  legal, publication, keys, secrets, root rights, security rules, money and irreversible actions still asked) applies here
  too; CLAUDE.md's "Decisions" line is unchanged until the owner amends it.
- 2026-10-27, branch `claude/software-update-step1` (Software Update step 1b, the infrastructure of grassfield ADR-0033,
  whose client is grassfield PR #16): PR to main; nothing published, no secret, no tag, no release.
  - `keyring/`: grassfield-keyring, files in `/usr/share/grassfield/pacman-keyring/`, populate-from only with keys and only
    while `/etc/pacman.d/grassfield.conf` exists, `pre_remove` deletes its trusted keys; NO KEY until O11 (empty files).
  - `build/pacman.conf`: Omarchy's stable mirror (Hyprland 0.56.2-4, quickshell 0.3.2-1, Qt 6.11.2, KF6 6.31 in [extra]).
  - `scripts/build-channel.sh` (grassfield's own PKGBUILD, keyring built first, names and replaces checked, packages,
    databases and notes signed, `repo-add --prevent-downgrade`, immutable package names, snapshot + pointer, build record),
    `notes.py`, `check-tree.sh`, `rollback.sh`, `view.sh`, `serve.py`.
  - `.github/workflows/`: build (workflow_dispatch: build with a throwaway key, check-tree, artifact; test: smoke.sh),
    publish (the one serialized publisher per channel of ADR-0033 h.2 as amended by ADR-0037 g, merged from PR #1 while
    PR #3 was open: the latest state, built from the current snapshot with `build-channel.sh --channel`, the pointer
    written with If-Match, started again when it moved; `if: false`), poll (every 15 min, off until
    `GRASSFIELD_TAG_POLL=on`), watch-hyprland (by hand only). Not run: no deploy key exists, and nothing may be published.
    `tests/newest-release.sh` (the publisher's choice of release, in a container): 9 PASS.
  - Tests (outputs in `docs/evidence/step1b-2026-10-27/`):
    - `tests/e2e.sh` with the REAL packages built three times (1.0.0, 1.0.1, 1.1.0-beta1 of grassfield's step 1 client):
      exit 0, 72 PASS, 0 FAIL (first installation per ADR-0033 b.3a, Set Up through real pkexec, updates seen with
      verified notes and installed, rogue database, packages and notes refused, beta and back without a downgrade,
      rollback over HTTP by a new snapshot, removal, the keyless keyring trusting nothing);
    - the build job's script and `tests/smoke.sh` (the CI path, run locally): build exit 0, check-tree 0 failures, smoke
      0 failures; a ref without release notes is refused.
  - The first clean builds found two gaps in grassfield's PKGBUILD makedepends, fixed in grassfield #16 (8509be8, 0338116).

## Tests run
- Store step 0: none (docs only). Software Update step 1b: see its entry above (end-to-end 72 PASS, the CI path).

## Open
- From the owner, later: `GRASSFIELD_DEPLOY_KEY`, then `GRASSFIELD_TAG_POLL=on`; the `release` environment and its
  secrets (signing key and passphrase, S3 keys) and variables (bucket, endpoint); the public key and fingerprint; the host.
- The workflows have never run on GitHub (they need the deploy key); their steps ran locally only through the scripts.
- Pruning of old snapshots (7 days) and of packages no snapshot names: with hosting, after M5.

## Next
- Software Update step 1b (ADR-0033): the integrator's review of PR #3 (opus for signing, keyring and CI); then grassfield's
  one-line follow-up adding grassfield-keyring to grassfield-desktop's depends (O21); step 2 (the pane) in grassfield after
  its Settings PRs #8-#10.
- Grassfield Store step 1 (ADR-0037): `catalog/` sources, the build and validation tool (standard-library Python), a CI job
  producing the signed catalog with a throwaway key; the catalog joins `publish.yml`, the one serialized publisher per
  channel written (disabled) by step 1b.
