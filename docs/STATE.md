# Grassfield packages — Current State
Last updated: 2026-10-27

## Done
- Repository created (private) with README, LICENSE (MIT), CLAUDE.md and this file.
- 2026-10-27, branch `claude/software-update-step1` (Software Update step 1b, the infrastructure of grassfield ADR-0033,
  whose client is grassfield PR #16): PR to main; nothing published, no secret, no tag, no release.
  - `keyring/`: grassfield-keyring, files in `/usr/share/grassfield/pacman-keyring/`, populate-from only with keys and only
    while `/etc/pacman.d/grassfield.conf` exists, `pre_remove` deletes its trusted keys; NO KEY until O11 (empty files).
  - `build/pacman.conf`: Omarchy's stable mirror (Hyprland 0.56.2-4, quickshell 0.3.2-1, Qt 6.11.2, KF6 6.31 in [extra]).
  - `scripts/build-channel.sh` (grassfield's own PKGBUILD, keyring built first, names and replaces checked, packages,
    databases and notes signed, `repo-add --prevent-downgrade`, immutable package names, snapshot + pointer, build record),
    `notes.py`, `check-tree.sh`, `rollback.sh`, `view.sh`, `serve.py`.
  - `.github/workflows/`: build (workflow_dispatch: build with a throwaway key, check-tree, artifact; test: smoke.sh;
    publish written, `if: false`), poll (every 15 min, off until `GRASSFIELD_TAG_POLL=on`), watch-hyprland (by hand only).
    Not run: no deploy key exists, and nothing may be published.
  - Tests: `tests/e2e.sh` (see the PR for its run), `tests/smoke.sh` (CI's test job).

## Open
- From the owner, later: `GRASSFIELD_DEPLOY_KEY`, then `GRASSFIELD_TAG_POLL=on`; the `release` environment and its
  secrets (signing key and passphrase, S3 keys) and variables (bucket, endpoint); the public key and fingerprint; the host.
- The workflows have never run on GitHub (they need the deploy key); their steps ran locally only through the scripts.
- Pruning of old snapshots (7 days) and of packages no snapshot names: with hosting, after M5.
- PR #1 (the Store catalog) edits README, CLAUDE.md and this file too: whichever merges second merges the other.

## Next
- The integrator's review (opus for signing, keyring and CI) of this PR and of grassfield #16.
- Step 2 (the pane) in grassfield after its Settings PRs #8-#10.
