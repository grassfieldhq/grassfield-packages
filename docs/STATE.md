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
  - `scripts/build-channel.sh`:
    - grassfield's own PKGBUILD, keyring built first and once per version;
    - names and `replaces=` checked; packages, databases and notes signed with throwaway keys only (it refuses to start
      beside the project's key);
    - the release build; immutable package names; never a package older than the current snapshot's;
    - snapshot and pointer in the publisher's format (`snapshot.py`); the build record.
    Beside it: `notes.py`, `check-tree.sh` (`--trusted`), `sign-release.sh`, `snapshot.py`, `rollback.sh` (withdraws the
    newer release builds), `view.sh`, `serve.py`.
  - `.github/workflows/`, every action pinned to a commit SHA. Not run: no deploy key exists, and nothing may be
    published.
    - build (workflow_dispatch, a tag or a pkgrel rebuild):
      - build: a throwaway key, check-tree, the artifact;
      - test: smoke.sh;
      - release, `if: false`, per channel in the publisher's environments `publish-<channel>`: the tested release build
        signed with the project's key in a container that runs no build, checked with `check-tree --trusted`, and kept
        under `releases/` (never replaced, its database last).
    - poll: every 15 min, off until `GRASSFIELD_TAG_POLL=on`.
    - watch-hyprland: by hand only.
  - Publication: the one serialized publisher per channel is Grassfield Store step 1's (ADR-0037 g and its Consequences;
    PR #2's `publish.yml` and `tools/publish.py`). This PR's own `publish.yml` (written while resolving the conflict with
    PR #1) rebuilt each tag at publication, against ADR-0037 g ("each tag is built once", its packages, databases and notes
    kept where the publisher reads them), and doubled PR #2's: removed, with `newest-release.sh`, its test and
    `--channel`. Instead `build-channel.sh` writes each release build `releases/<channel>/<version>/` (a database of the
    release alone, notes with the channel's earlier releases from the tag's own tags, grassfield-keyring built once per
    version), the layout `tools/publish.py --releases` reads, and makes the test tree's snapshots from it as the
    publisher does.
  - After the integrator's opus review of e373590 (FAIL: 1 BLOCKER, 5 MAJOR, minors; integrator decision: PR #2 merges
    first, then this branch merges main and makes its `tools/publish.py` the only publisher):
    - B1: the test tree uses the publisher's format: pointer `{"snapshot": "<id>"}` and `manifest.json`. The catalog is
      kept in each new snapshot. The release job uses the `publish-<channel>` environments. Nothing is rebuilt at
      publication.
    - M1: the project's key never meets a build.
    - M2: a stored release build is never replaced; a published package is used as it is (the counter-case is refused by
      `tools/publish.py`).
    - M3: a rollback withdraws the newer release builds.
    - M4: `check-tree --trusted`.
    - M5: the pkgrel path is fixed and tested end to end.
    - Minors: actions pinned and credentials per step; stronger assertions, and a skip in CI fails; `--to` validated;
      the evidence re-recorded with its commits.
  - Tests on 3a6a138, grassfield main ae121e8 (outputs and commands in `docs/evidence/step1b-2026-10-27/`):
    - `tests/e2e.sh` with the REAL packages built four times (1.0.0, 1.0.1, 1.0.1 pkgrel 4, 1.1.0-beta1): exit 0, 43
      checks (330 PASS lines with check-tree's), 0 FAIL.
      It covers:
      - the first installation per ADR-0033 b.3a, and Set Up through real pkexec;
      - updates seen with verified notes and installed, and the pkgrel rebuild's note;
      - a rogue database, packages and notes refused;
      - beta and back without a downgrade;
      - a rollback over HTTP by a new snapshot, with the newer release builds withdrawn;
      - removal, and the keyless keyring trusting nothing;
    - `tests/release-build.sh`: exit 0, 17 checks, 0 FAIL;
    - the CI path, run locally (build job's inline script and `tests/smoke.sh`, v1.0.0-rc1 and v1.0.0-rc2 in fresh
      trees): exit 0, 0 failures each;
    - interface with PR #2's `tools/publish.py` (e05f23e, unmerged): the release builds signed and published, a client
      installing rc1 then rc2; without `--published` the publisher refuses: exit 0, 15 checks, 0 FAIL;
    - gitleaks v8.18.4 on origin/main..HEAD and on the tree: no leaks found.
  - The first clean builds found two gaps in grassfield's PKGBUILD makedepends, fixed in grassfield #16 (8509be8, 0338116).

## Tests run
- Store step 0: none (docs only). Software Update step 1b: see its entry above (end-to-end, release-build, the CI path,
  the interface with PR #2's publisher).

## Open
- From the owner, later: `GRASSFIELD_DEPLOY_KEY`, then `GRASSFIELD_TAG_POLL=on`; the publisher's environments
  `publish-stable` and `publish-beta` and their secrets (signing key and passphrase, S3 keys) and variables (bucket,
  endpoint); the public key and fingerprint; the host.
- The workflows have never run on GitHub (they need the deploy key); their steps ran locally only through the scripts.
- After PR #2 merges (integrator decision): merge main here; its `tools/publish.py` replaces `snapshot.py write` in
  `build-channel.sh` and `rollback.sh`; its `publish.yml` reads `releases/<channel>/` from the storage. A deliberate
  rollback (ADR-0033 h.2) is still outside the publisher, which refuses an older database.
- Pruning of old snapshots (7 days) and of packages no snapshot names: with hosting, after M5.

## Next
- Software Update step 1b (ADR-0033): the integrator's review of PR #3 (opus for signing, keyring and CI); then grassfield's
  one-line follow-up adding grassfield-keyring to grassfield-desktop's depends (O21); step 2 (the pane) in grassfield after
  its Settings PRs #8-#10.
- Grassfield Store step 1 (ADR-0037, PR #2): the catalog and the one serialized publisher per channel (`publish.yml`,
  `tools/publish.py`), which reads PR #3's release builds; PR #2 merges first, then PR #3 merges main (integrator).
