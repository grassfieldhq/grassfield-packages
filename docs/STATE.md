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
  whose client is grassfield PR #16): PR #3 to main; nothing published, no secret, no tag, no release.
  - `keyring/`: grassfield-keyring, files in `/usr/share/grassfield/pacman-keyring/`, populate-from only with keys and only
    while `/etc/pacman.d/grassfield.conf` exists, `pre_remove` deletes its trusted keys; NO KEY until O11 (empty files).
  - `build/pacman.conf`: Omarchy's stable mirror (Hyprland 0.56.2-4, quickshell 0.3.2-1, Qt 6.11.2, KF6 6.31 in [extra]).
  - `scripts/build-channel.sh`: one tag built once with grassfield's own PKGBUILD:
    - grassfield-keyring is built first, and once per version;
    - names and `replaces=` are checked; packages, databases and notes are signed with throwaway keys only (it refuses
      to start beside the project's key);
    - it writes the release build `releases/<channel>/<version>/`: a database of the release alone, and notes with the
      channel's earlier releases from the tag's own tags;
    - the channel tree is written by the one publisher, `tools/publish.py --releases`; then the build record.
  - The other scripts:
    - `notes.py`;
    - `check-tree.sh`: `--trusted` checks signatures as a client does; `--keyring-src` checks the keyring byte for
      byte; manifests; a release build holding nothing else;
    - `sign-release.sh`: `prepare` without the key, `sign` with gpg only;
    - `keyring-check.sh`: grassfield-keyring against `keyring/`, the whole package;
    - `rollback.sh`: the newer release builds withdrawn, then `tools/publish.py --rollback-to`;
    - `snapshot.py`: reads the pointer;
    - `view.sh`, `serve.py`.
  - Publication: the one serialized publisher per channel is `tools/publish.py` and `publish.yml` (ADR-0037 g), merged
    from PR #2.
    - This branch merged main (6b6a755, integrator decision) and made it the only writer of snapshots.
    - It added ADR-0033 h.2's deliberate rollback to the publisher (`--rollback-to`, 2 unit tests).
    - It extended `publish.yml` to package snapshots: it starts when the build workflow completes, and reads the
      release builds from `releases/<channel>/`.
    - This branch's own earlier `publish.yml` (rebuilt each tag at publication) and `newest-release.sh` are gone.
  - `.github/workflows/build.yml` (actions pinned to commit SHAs; not run: no deploy key exists, and nothing may be
    published). On demand, a tag or a pkgrel rebuild:
    - build: a throwaway key, check-tree, the artifact;
    - test: `smoke.sh`;
    - release, `if: false`, per channel in `publish-<channel>`:
      - exact-key lookups;
      - prepare in a container without the key or network;
      - sign in a container with the key, gpg only, no network;
      - check without the key (`check-tree --trusted --keyring-src keyring/`);
      - upload under `releases/`, the database last, never replacing a stored release build.
    - `poll` (off until `GRASSFIELD_TAG_POLL=on`) and `watch-hyprland` (by hand).
  - Integrator reviews:
    - Opus review of e373590: FAIL (B1, M1-M5, minors), all addressed (comment 6439709205).
    - Counter-review of a0a1cad: FAIL (one MAJOR left, M1: repo-add evaluates .PKGINFO lines, and ran where the key was;
      minors 1-4), addressed in 620e487..08a6677:
      - signing in two steps and three containers;
      - a crafted-package test;
      - head-object lookups;
      - the keyring compared with `keyring/`;
      - checks counted by the tests themselves.
    - The unification after PR #2's merge (comment 6440650953): 6b6a755..d7a6d2e.
    - PR #4's merge (b4032fb, the publisher checks every signature before use): 9520c98, 9a87253.
    - Counter-review of 9a87253: no BLOCKER or MAJOR in the code; FAIL because nothing at the head was run and recorded.
      Minors 1-3 fixed in d844f07..7744988:
      - the publisher checks the rollback's snapshot id;
      - the keyring is compared with `keyring/` as a whole package;
      - a refused rollback withdraws nothing.
    - Counter-review of 627e70e: minors 1-3 FIXED; new MINOR (a symbolic link passed keyring-check as an empty file)
      fixed in e995289. Every test below was run at e995289 and its output is recorded.
  - Tests at e995289 (outputs, commands and commits in `docs/evidence/step1b-2026-10-27/`; grassfield main ae121e8):
    - `tests/run-in-container.sh`: `Ran 52 tests … OK`, nothing skipped;
    - `tests/release-build.sh`: exit 0, 34 checks, 0 failures;
    - `tests/e2e.sh`, the REAL packages built four times (1.0.0, 1.0.1, 1.0.1 pkgrel 4, 1.1.0-beta1): exit 0, 44
      checks, 0 failures;
    - `ci-path.sh`, with `keyring/` as after O11: exit 0, 23 checks, 0 failures;
    - `tests/smoke.sh` on its two builds: exit 0, 6 checks, 0 failures each;
    - gitleaks on origin/main..HEAD and the tree: no leaks found; GitHub's `check` job green on each push.
  - The first clean builds found two gaps in grassfield's PKGBUILD makedepends, fixed in grassfield #16 (8509be8, 0338116).

- 2026-10-27, Grassfield Store step 1 (this repository's half; ADR-0037 passed opus review, grassfield b8e97aa, this repository
  c14b14a), branch claude/pensive-thompson-fhk5um from main:
  - `catalog/`: categories (9), the Discover section, 13 apps (8 Arch packages, 2 `[omarchy]` packages, 3 Omarchy setups:
    Firefox, Steam, Heroic), the pinned Omarchy release (v4.0.4, c668141); our texts in English and French; no icon yet.
  - `tools/catalog.py`: every rule of ADR-0037 g (format, lengths, plain text, patterns of e.5, cross-references), the
    sources' own rules (file names, icons as PNG within 256 KiB and 512x512 with licence, origin and the legal-review mark),
    `check-env` against facts (the repository and package of each app on Omarchy's stable mirror, an application entry for
    each package (SD1), the desktop id among its entries, the AppStream id spelled as AppStream spells it, recipes present in
    the pinned release with a case for each argument, never syncing nor downloading code through anything they call or
    source, Flathub ids), a deterministic build (`generated` from the serial), signing, and the Store's verification
    (gpgv, VALIDSIG's argument 10 in grassfield-trusted, not in grassfield-revoked, channel, serial, icon hashes).
  - `tools/catalog-facts.sh`: the facts, in a throwaway Arch container on Omarchy's stable configuration (the AppStream
    package checked by `pacman-key --verify`).
  - `tools/publish.py`: one publisher per channel that publishes the latest state, builds from the current snapshot, never
    goes backwards, uploads immutable names once and writes the pointer by compare-and-swap; `LocalStore` only (the
    bucket's backend waits for the host, O8); disabled in CI.
  - `.github/workflows/catalog.yml`: tests, checks, both channels built, signed with a throwaway key and verified, kept as
    an artifact 7 days; the publish job `if: false`, no secret. Actions pinned by commit.
  - Carried into step 3 (integrator, PASS of step 0): SD2's sheet keeps "Action: <id>" and the helper's path under the
    plain words; the helper's `install` applies SD1's app-entry rule too, or the gap is accepted in writing.
- 2026-10-27, after the opus review of step 1 (FAIL, 1 MAJOR and 10 minors, PR #2):
  - MAJOR: every language of a web app's `name` follows the web-app name rule (1 to 64 characters, no `/`, no leading `.`,
    no control or format character), tested through `validate_catalog`.
  - Plain text refuses format characters (zero-width, BOM, soft hyphen), U+2028/2029 and markup (`<`, `>`, `&entity;`);
    URLs are parsed (a valid lower-case host, no user information, a valid port); keyring lists are read whatever their
    case and spacing; malformed types are problems, never crashes, and the command line ends in one line, exit 2.
  - Recipes: any `-y` cluster or `--refresh`/`--sysupgrade` on pacman, yay or paru, a `yay` without an operation, `git
    clone`, `makepkg`, `yay -G`/`-B`, and an AUR build (`omarchy-pkg-aur-add` or `yay -S` of a name no repository serves, or
    known only at run time). The 63 recipes of the pinned release: still the 4 the ADR names refused.
  - Publisher: the catalog must pass the Store's own checks for the channel first (`--keyring-dir`; signature, rules,
    icons); the decision is on a content hash (serial and build time aside) recorded as `catalogContent`, so a rebuilt
    catalog is nothing new; only the icons the signed file lists are uploaded.
  - `.github/workflows/publish.yml`: the publishing job in its own workflow (push to main only, `if: false`, a failing first
    step, a protected `publish-<channel>` environment per ADR-0033 b.7, one concurrency group per channel, never cancelled
    in progress, main's head checked out when the run starts, no secret); `catalog.yml` has the check job only.
  - Tests: truncated catalog and `.sig`, empty and missing `.sig`, a signer absent from the keyring, an oversize file.
  - Category names made neutral (minor 10): "Graphics" / « Graphisme », "Photos and Video" / « Photos et vidéo », "Music and
    Audio" / « Musique et audio », "Development" / « Développement ».

- 2026-10-27, step 1 merged after the opus counter-review's PASS (main b76bebe). The follow-up the integrator asked for
  before publishing is ever enabled (branch claude/pensive-thompson-fhk5um restarted from main, its own PR):
  - Keyring lists fail closed: a line that is not a fingerprint (grouped, `0x`, a trailing comment) makes the whole list
    unreadable, so nothing signed is used; a signature file with two signers is refused, as the Store refuses it.
  - Recipes are read as shell: continuations joined, quotes removed, every command found after its wrappers (`sudo -u x`,
    `env`, `command`, `exec`, `timeout`...), and quoted text and `-c` arguments read as commands too. A bare `paru`, `git -C
    d clone/pull/fetch` and the language installers (mise except its read-only commands, npm, npx, pipx, pip, cargo, uv,
    go, gem) now count. Over the 63 recipes of v4.0.4, 11 are refused (4 before): Hermes (through `mise`), T3 Code,
    the preinstalls and Helix reach `omarchy-install-hermes-cli` or `omarchy-mise-install` through what they call. The
    three setups the catalog names still pass (`check-env: ok`).
  - The publisher checks every file of a release (databases, notes, packages) with gpgv against the keyring before
    uploading anything; `--keyring-dir` is required.
  - A deeply nested JSON file is a one-line problem (RecursionError), never a traceback.
  - `publish.yml` and STATE name the owner's step: create and protect the `publish-<channel>` environments before
    `if: false` is removed (GitHub creates a missing one unprotected).
  - After the review of ed69656 (FAIL, the recipe check did not fail closed), the integrator's decision: the pins are the
    control. `catalog/omarchy.lock` records the SHA-256 of every Omarchy file the setups run or read (43 for v4.0.4's
    browser, Steam and Heroic setups, written by `catalog.py pin` in a throwaway container against the checkout at
    c668141); check-env refuses any file that differs, is missing or is not pinned. The scan is the second line, rewritten
    as a shell reader that fails closed (comments and heredoc bodies apart, `$(...)`, backquotes, process substitutions,
    arithmetic, `[[ ]]`, `case` patterns and arrays read as the shell reads them): it refuses text it cannot read, `eval`,
    a script read from a pipe or a heredoc, a command made by a substitution, an Omarchy command named at run time,
    pacman's options known only at run time, `-U`, the starts of `--refresh`/`--sysupgrade`, aria2c, rsync, flatpak and
    their kin, `git submodule`, an interpreter's network code; a variable set only to literal text is resolved (`pm=pacman;
    $pm -Sy` is a sync); one it cannot resolve is printed by pin for the person reading ("read: …", 4 for v4.0.4). Over
    Omarchy v4.0.4's 63 recipes, 22 are refused; the catalog's three setups pass. The publisher verifies a release's
    signatures before bsdtar reads its database.
  - **The 43 pinned files still need a person's reading** (the pin says nobody changed them, not that they are safe): the
    owner's or the integrator's, before publishing is enabled.
  - Parity with grassfield PR #21's review: a `.sig` that is a signed message of its own (PLAINTEXT) is refused;
    `catalog-facts.sh` checks Arch's AppStream package with gpg on a copy of pacman's keyring (one good detached signature,
    TRUST_FULLY or TRUST_ULTIMATE, the key not disabled) instead of `pacman-key --verify`, whose exit code is 0 for any key
    of the keyring, trusted or not (grassfield ADR-0037 S19). Arch's real package passes it (1604 components read).

## Tests run
- Software Update step 1b: see its entry above (unit tests, release-build, the end-to-end, the CI path with keyring/ as
  after O11, GitHub's `check` job).
- Store step 1 follow-up: `tests/run-in-container.sh --network host`: `Ran 46 tests … OK`, exit 0, nothing skipped (47 with
  the parity commit, in the CI replay). The CI check job replayed in a throwaway container: docker exit 0 (`validate: ok`,
  `check-env: ok`, both channels built, signed with a throwaway key and verified).
- Store step 1 review fixes: `tests/run-in-container.sh --network host` (throwaway archlinux:base container): `Ran 40 tests
  … OK`, exit 0, nothing skipped (the signature and publisher tests make throwaway ed25519 keys there). Outside a
  container: `Ran 40 tests … OK (skipped=21)`. `python3 -I tools/catalog.py validate`: ok.
- Store step 1: `tests/run-in-container.sh` (throwaway archlinux:base container): 28 tests OK (the signature tests make
  throwaway ed25519 keys there). The CI check job replayed step by step in a throwaway container: docker exit 0 (validate
  ok, 15792 packages, 41 entries and 1604 AppStream components gathered, check-env ok, both channels built, signed,
  verified).
- Store step 0: none (docs only).

## Open
- From the owner, later: `GRASSFIELD_DEPLOY_KEY`, then `GRASSFIELD_TAG_POLL=on`; the publisher's environments
  `publish-stable` and `publish-beta` and their secrets (signing key and passphrase, S3 keys) and variables (bucket,
  endpoint), created and protected before `if: false` is removed (below); the public key and fingerprint; the host, and
  with it the bucket's backend of `tools/publish.py`.
- The workflows have never run on GitHub (they need the deploy key); their steps ran locally only through the scripts.
- Pruning of old snapshots (7 days, `tools/publish.py`) and of packages no snapshot names: with hosting, after M5.

## Open questions (owner)
- **Legal (ask the owner; never settled by an agent):** may the Store's category names follow the Mac App Store's own list
  ("Graphics & Design", "Photo & Video", "Developer Tools"), or stay neutral? The catalog uses neutral names until the owner
  decides; "Productivity", "Games", "Education" and "Utilities" are common to most stores but are in that list too. The
  section and category names and the publishers' icons need the M5 legal review before any publication (ST10).

## Owner steps before publishing is enabled
- Create the `publish-stable` and `publish-beta` environments with required reviewers (the owner approves each run) and
  deployments from `main` only, then add the channel's key and storage credentials there (ADR-0033 b.7). GitHub creates a
  missing environment unprotected when a job that names it runs, so this comes before `if: false` is removed.

## Next
- Software Update step 1b (ADR-0033): the integrator's re-review of PR #3 (the counter-review's fixes, the unification and
  the merge of #4); then grassfield's one-line follow-up adding grassfield-keyring to grassfield-desktop's depends (O21);
  step 2 (the pane) in grassfield after its Settings PRs #8-#10.
- The Store's later steps add to the catalog (more sections, icons for apps without metadata after the legal review).
