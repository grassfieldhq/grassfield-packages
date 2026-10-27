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

- 2026-10-27, PR #4 merged with PASS (b4032fb). The five MINORs its merge comment left, before publishing is enabled
  (branch restarted from main, its own PR):
  1. The closure: Omarchy's other names for its folder (`$OMARCHY_INSTALL`, `/usr/share/omarchy/`,
     `~/.local/share/omarchy/`, `$HOME/.local/share/omarchy/`) are followed; the scan refuses an Omarchy command or a
     sourced file the closure did not follow (a split name like `"omar""chy-x"` or `omar\chy-x`, a path with a variable
     segment, a file outside Omarchy's folder).
  2. A backslash at a line's end joins the lines with nothing, as bash does (`pac\<newline>man -Sy` is a sync).
  3. `gum ... -- COMMAND`, `systemd-run`, `runuser`, `chroot`, `unshare` and `watch` are read as wrappers; pacman's
     arguments made by a substitution (`pacman -S $(cat list)`) are refused; from an array or the script's own arguments
     (`"${pkgs[@]}"`, `"$@"`), a note for the person reading.
  4. `pin` reads the checkout's commit from `.git` or `.commit` (as catalog-facts.sh does) and refuses when neither
     names the lock's commit.
  5. The comment says what the scan does with a command named by a variable: resolved, or listed, not refused.
  The pin step on v4.0.4 in a throwaway container: `nothing changed` (the same 43 files), 7 notes to read.
- Carried to grassfield's install step (the Store app, step 3; integrator, PR #4): the pins cover the reviewed release in
  CI only, so before running a setup the Store refuses it when the installed Omarchy differs from the pinned release, with
  a plain message.

## Tests run
- Step 1 follow-up: `tests/run-in-container.sh --network host`: `Ran 46 tests … OK`, exit 0, nothing skipped (47 with the
  parity commit, in the CI replay). The CI
  check job replayed in a throwaway container: docker exit 0 (`validate: ok`, `check-env: ok`, both channels built,
  signed with a throwaway key and verified).
- Step 1 review fixes: `tests/run-in-container.sh --network host` (throwaway archlinux:base container): `Ran 40 tests … OK`,
  exit 0, nothing skipped (the signature and publisher tests make throwaway ed25519 keys there). Outside a container:
  `Ran 40 tests … OK (skipped=21)`. `python3 -I tools/catalog.py validate`: ok.
- Step 1: `tests/run-in-container.sh` (throwaway archlinux:base container): 28 tests OK (the signature tests make throwaway
  ed25519 keys there). The CI check job replayed step by step in a throwaway container: docker exit 0 (validate ok,
  15792 packages, 41 entries and 1604 AppStream components gathered, check-env ok, both channels built, signed, verified).
- Step 0: none (docs only).

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
- The integrator's review of the step-1 follow-up PR.
- ADR-0033's half of this repository (its own step): building from a Grassfield tag in a clean Arch container, signing,
  `grassfield-keyring`, `repo-add` per channel, CI producing the channel repository as an artifact; publish.py's release
  folders are what that build leaves. No publication.
- The Store's later steps add to the catalog (more sections, icons for apps without metadata after the legal review).
