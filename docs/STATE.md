# Grassfield packages — Current State
Last updated: 2026-11-05

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
    - `poll` (off until `GRASSFIELD_TAG_POLL=on`) and `watch-hyprland` (the toolkit watch, daily since 2026-11-08: ABI stamp, quickshell, qt6-base against Omarchy stable and rc).
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
- 2026-10-27, Grassfield Store step 2 (this repository's half, branch `claude/pensive-thompson-fhk5um` restarted from main
  b0e8494; grassfield's half is the Store's UI):
  - The catalog: four sections after Discover (`create` 20, `work` 30, `play` 40, `develop` 50), each with a hero, cards
    and rows in our own words, English and French; ten apps from [extra] (darktable, Rnote, KeePassXC, Signal, Foliate,
    0 A.D., SuperTuxKart, Godot, Meld, DBeaver), each with its categories. No icon, no publisher's text.
  - The two gaps of PR #5's merge comment, in the scan behind the pins:
    1. A file run by a shell (`bash "$OMARCHY_PATH/install/missing.sh"`, `sh -e "$OMARCHY_PATH/$h/run.sh"`) or by its
       path (`"$OMARCHY_PATH/install/x.sh"`, a path made at run time) is refused unless the closure pinned it; a shell's
       options are read (`-ec TEXT` is read as text, `-o pipefail FILE` runs FILE, `-s` and `-` read the input).
    2. An argument that names a package manager or a downloader, literally or through a variable set only to literal text,
       is refused when the command it is handed to is not one the scan knows (`firejail`, `strace`, `bwrap`, `parallel`,
       `systemd-inhibit`...); commands that take a name as data (`echo`, `pgrep`, `chmod`, Omarchy's package helpers) are
       listed. A plain variable as pacman's argument (`"$pkg"`, which could be `-y`) is a note for the person reading.
  - Evidence: the pin step on v4.0.4 (c668141) in a copy of `catalog/`: `nothing changed`, exit 0, the lock byte for byte
    the same, 10 notes (the 7 before and three `pacman -Q "$pkg"` in `omarchy-pkg-add`, `omarchy-pkg-aur-add` and
    `omarchy-pkg-missing`, queries over `for pkg in "$@"`).
- 2026-10-27, PR #6 merged with PASS (1b51303). The two scan gaps its merge comment left (branch restarted from main, its
  own PR):
  1. A file run by a relative or foreign path (`cd "$OMARCHY_PATH/install" && ./hidden.sh`, `/tmp/x.sh`) is refused;
     programs in the system's folders are still judged by name. A `PATH` assignment (a prefix, `env PATH=`, `export
     PATH=`) naming a folder other than the system's, `$OMARCHY_PATH/bin` and `$PATH` is refused, an empty entry (the
     current folder) too.
  2. A variable or a substitution the scan cannot resolve, handed whole to a command it does not know, is a note
     (`pm=$(command -v pacman); firejail $pm -Sy`, `firejail "$pm"` with `pm` never set, `gum spin --title t $pm -Sy`
     without `--`, which is now read like any other command). Not noted: calls to Omarchy's commands and to the closure's
     own shell functions (read where they are written; one that runs its arguments has its note there) and commands that
     take values as data (`NAMES_AS_DATA`, now with `jq`, `head`, `kill`, `exit`...). A literal name after a variable
     prefix (`"$d/pacman"`) is refused like a literal one.
  The scan on v4.0.4 (c668141): the six setups pass; 19 notes (the 10 before, and 9 new: `sed`, `ffmpeg`, `yt-dlp`,
  `quickshell` and `qs` handed a variable in the browser, monitor and shell helpers).
- 2026-10-27, branch `claude/grassfield-software-update-dj2bvt` (the follow-up of grassfield PR #24, grassfield ADR-0033 O22:
  grassfield-desktop depends on grassfield-keyring; integrator review of grassfield #24's 532fb8f):
  - `scripts/build-channel.sh` refuses a release whose grassfield-desktop `.PKGINFO` lacks `depend = grassfield-keyring`
    (a grassfield ref from before #24), and `scripts/check-tree.sh` refuses a set whose database's grassfield-desktop does
    not depend on it (the CI build check and the release job's third container);
  - `keyring/grassfield-keyring.install`: `pre_remove` reads a last line without its newline too (`|| [ -n "$fpr" ]`), or,
    after O11, that key would stay trusted after removal; grassfield-keyring 20261027-2 (pkgrel 2: a changed install
    script); `build-channel.sh` reuses a built keyring only while it is still `keyring/`'s, the whole package
    (`keyring-check.sh`, no longer the three files only), so such a change without a new pkgrel stops the build;
  - `tests/e2e.sh` and `tests/smoke.sh`: the client names grassfield-desktop, -compositor and -icons only, and gets
    grassfield-keyring "Installed as a dependency for another package"; `tests/release-build.sh` reads the keyring's
    version from `keyring/PKGBUILD`, its fake grassfield-desktop depends on the keyring, and it checks the refusal and the
    install script's last line.
  - Evidence: `docs/evidence/o22-2026-10-27/`.
- Carried to grassfield's install step (the Store app, step 3; integrator, PR #4): the pins cover the reviewed release in
  CI only, so before running a setup the Store refuses it when the installed Omarchy differs from the pinned release, with
  a plain message.
- 2026-10-28, Grassfield Store step 3b1 (this repository's half; branch `claude/pensive-thompson-fhk5um` restarted from main
  afe089c after grassfield PR #30's merge; grassfield's half is grassfieldhq/grassfield PR #34, ADR-0037 g amended there):
  - The catalog publishes the release and the pins (`"omarchy": {"tag", "commit", "files"}`, read from `omarchy.lock`), so
    the Store can refuse a setup when the installed Omarchy differs from them (the note carried from PR #4 above).
    `validate_catalog` requires the object when the catalog has a setup, with both of its recipes pinned (`bin/<name>`),
    a tag like v4.0.4, a 40-digit commit, 1 to 512 relative paths without `.` or `..` segments and their SHA-256;
    `catalog.py pin` does not check it (it writes the pins).
  - The scan gap of PR #7's merge (task 31): the command `find -exec`, `-execdir`, `-ok` or `-okdir` runs is read as a
    command (a lone `\;`, `';'` or `";"` is find's terminator, not the shell's separator), the files `find` finds, run or
    handed to a shell, are refused, and so is `run-parts` (except `--test` and `--list`).
  - The validation patterns end with `\Z`: `$` also matched before a final line feed, so a package name, a recipe or an
    argument ending with one passed CI (grassfield's Store already validates the catalog with `\A…\z`; its two package
    name checks and its operation id check used `^…$` and are fixed in its half of this step).
  - Tests: `tests/run-in-container.sh`: 58 tests, OK (Rules.test_omarchy, Rules.test_no_line_end_after_a_token,
    Recipes.test_what_pr_7s_merge_left new; each of the three scan changes reverted alone fails the new test). The three
    setups of Omarchy 4.0.4 still pass the scan, and their 43 pins match (`find -exec rm -rf -- {} +` in
    `install/helpers/browser-policy.sh` is read and accepted).
  - The integrator's review of PR #10 (opus, FAIL, one MAJOR): the find rule read only the first word after `-exec`, so a
    wrapper in front of `{}` (`sudo`, `env`, `setsid`, `nohup`, `timeout 9`, `uwsm-app --`, `busybox sh`), a `+` that does
    not follow `{}` (`-exec sh -c '"$1"' + {} \;`) and `run-parts -a --list DIR` passed. Now an action handed `{}` must
    be, after its wrappers, one of FIND_HANDS (commands that copy, move, remove, change or read a file: rm, cp, chmod...),
    else it is refused; what it runs is still read as a command; `+` ends it only right after `{}`; `run-parts` is
    accepted only as exactly `--list DIR` or `--test DIR`. Tests: `tests/run-in-container.sh`: 58 tests, OK (each case of
    the review, and Omarchy's own `find "$dir" ... -exec rm -rf -- {} +`, in Recipes.test_what_pr_7s_merge_left); 6
    mutants of the rule (the first word only, no unwrapping, `+` anywhere, run-parts' old test, `sh` among FIND_HANDS,
    what a refused action runs not read) each fail it. The CI check job replayed in a throwaway container: `validate:
    ok`, the facts (15848 packages, 51 entries, 1604 AppStream components), `check-env: ok`, 43 pins.
  - The integrator's re-review of 91e7c66 (opus, FAIL, one MAJOR in the same class): the wrapper tables missed options
    that take an argument (`env -a`/`--argv0`, `xargs -E`, `sudo --prompt`, doas's `-a`, run0's `--description`), so
    the scan read that argument as the command (`-exec env -a rm bash {} \;` passed and ran the file; outside find,
    `env -a rm bash "$OMARCHY_PATH/hidden/run.sh"` too). Now each wrapper lists its options that take an argument and its
    flags; any other option is refused ("an option the scan does not know"), which also refuses those that run a command
    string of their own (`env -S`, `flock -c`, `runuser -c`, `sudo -s`/`-i`); `--opt=value` and grouped flags (`-nl`)
    are read. A find action handed `{}` runs no wrapper at all: its first word is one of FIND_HANDS. Tests: 58 OK (each
    case of the re-review with each of -exec, -execdir, -ok and -okdir; the outside-find case; nine unknown options
    refused; every wrapper form of Omarchy v4.0.4's files still read); 6 mutants of the change (an unknown option
    skipped, find unwrapping again, env's `-a` unlisted, timeout's `--kill-after` unlisted, no grouped flags, no `=`
    form) each fail them. The six recipes of the three setups pass the scan against the Omarchy 4.0.4 checkout and the
    43 pins match (catalog.recipe_problems and pin_problems, facts of 2026-10-27); the full CI replay could not fetch
    Omarchy's mirror (`extra.files` too slow, three tries), and with the facts of 2026-10-27 check-env reports only the 10
    catalog apps added since those facts were made.
  - Merged: grassfield #34 as d4332ab, this repository's PR #10 as 4adc276 (opus PASS on 9dee19e).
- 2026-10-28, follow-up of PR #10's merge (branch `claude/pensive-thompson-fhk5um` restarted from main 4adc276): the
  integrator's merge note (on grassfield #34): outside find, a command the scan does not know, handed a shell and a
  script, passed with no note (`chrt -f 1 bash "$OMARCHY_PATH/hidden/run.sh"`, `firejail bash …`); it predates PR #10.
  - A command the scan does not know (`runs_what_it_is_handed`: not one it reads its own way, not Omarchy's, not one that
    takes names as data) may run what it is handed. A shell or an interpreter there, by its name or a system folder's
    path, with words after it, is read as a command from that word on (`chrt -f 1 bash x.sh` is judged as `bash x.sh`, a
    `-c` text is read). Refused among its words: a file of Omarchy's the closure did not pin (one the release lacks), an
    Omarchy command the release lacks, a word with a script's suffix (`.sh`, `.py`, `.pl`, `.js`, `.lua`...) outside
    the pins. One of Omarchy's folders is a note ("its files are not pinned"). Its other words (a path in the home folder,
    a device) are data the scan cannot tell from a program: refusing every path there would refuse Omarchy's own `sed`,
    `mount` and function calls (the survey below).
  - Found on the way, the same class: an interpreter's own script was never judged (`python3 /tmp/x.py`, `perl ./x.pl`
    passed). Its first operand, after the options that take an argument (`-W`, `-X`, `-I`, `-r`), is now judged against
    the pins like a shell's; `-c`, `-e`, `-m` (alone or grouped, `-uc`) run text or a module, not a file.
  - `useradd`, `usermod` and `chsh` take a login shell as data (`-s /bin/bash`): with the names taken as data.
  - Survey of Omarchy v4.0.4 (c668141), all 63 `omarchy-install-*` and `omarchy-remove-*` recipes, the old scan against the
    new: no new problem, none gone; two new notes, both Omarchy's own Quickshell folder (`qs ipc -p "$OMARCHY_PATH/shell"`
    in `bin/omarchy-shell`, `systemd-cat … quickshell -p "$OMARCHY_PATH/shell"` in `bin/omarchy-launch-shell`), in the
    browser setup's closure. Its 183 files are not pinned; they are the running desktop's own shell, which the session
    runs anyway: a note for the person who pins, not a refusal (the integrator decides).
  - Tests: `tests/run-in-container.sh --network host`: `Ran 59 tests … OK`, exit 0 (Recipes.test_what_pr_10s_merge_left
    new: each case of the note, an interpreter's script, a shell function that runs its arguments, the cases read as
    before, the folder note); 10 mutants of the change each fail it. `validate: ok`; the six recipes of the catalog pass
    the scan against the Omarchy 4.0.4 checkout and the 43 pins match.
  - Merged as 22f4101 (opus PASS); two LOW limits recorded by the integrator: a command-string runner (`script -qc`,
    `su -c`, `tmux new`) handed `bash $OMARCHY_PATH/x` of a missing, suffix-less file; an unknown runner handed a
    suffix-less path outside Omarchy, data by design.
- 2026-10-28, Grassfield Store step 3b2, the AUR (this repository's half; branch `claude/pensive-thompson-fhk5um`
  fast-forwarded to main 22f4101; grassfield's half is its 3b2 PR, ADR-0037 SD21–SD23):
  - The AUR's two commands, Omarchy's `omarchy-pkg-aur-add` and `omarchy-pkg-drop` (`AUR_COMMANDS`), are pinned and
    scanned always, whether or not the catalog lists an AUR app: an AUR search result in the Store takes the same path,
    and the Store refuses an AUR operation unless both are pinned and match (SD21). `pin_files`, `pin` and `check-env`
    take them with the setups' recipes (`pinned_recipes`); `check-env` reports a finding as `AUR command <name>: …`.
    The lock is unchanged: both, and `omarchy-pkg-missing`, were already pinned through the setups.
  - `validate`: a catalog with an `aur` app needs the "omarchy" object and both commands pinned, with the
    `omarchy-pkg-missing` that `omarchy-pkg-aur-add` calls first (`AUR_PINS`; the integrator's note on grassfield #36: the
    Store requires the same, `requiredPins`).
  - `check-env` on an `aur` app: refused when a repository of Omarchy's stable mirror has the name (yay would install the
    repository's; the Store refuses it too) or when the AUR does not know it; `catalog-facts.sh` asks the AUR's web
    service (RPC v5 info) only when the catalog lists an AUR app, and keeps the name and version of each answer that
    reads as a package (`aur-packages.txt`; new command `catalog.py aur-packages`). The catalog lists none today.
  - catalog/README.md: the AUR source and the pins of its two commands; `omarchy.lock`'s comment.
  - Tests: `tests/run-in-container.sh --network host`: `Ran 59 tests … OK`, exit 0 (Rules.test_omarchy,
    Recipes.test_pins, Recipes.test_pin_command, Recipes.test_check_env and Sources.test_sources_pass_and_icons_resolve
    extended); 9 mutants of the change (each check removed, the commands left out of the pins or of either scan) each
    fail them. `validate: ok`;
    `pin` on Omarchy v4.0.4 in a copy of `catalog/`: `nothing changed`, exit 0, the same pins. The facts' AUR step, run
    alone against the AUR with `yay-bin visual-studio-code-bin gs-surely-not-on-the-aur`: exit 0, the two known names
    with their versions, the unknown one absent.
- 2026-10-30, Grassfield Store step 3c part 3, "Get Flatpak…" (this repository's half; branch
  `claude/pensive-thompson-fhk5um` restarted from main b2005ca; grassfield's half is its 3c part 3 PR, ADR-0037 SD24):
  - Get Flatpak's command, Omarchy's `omarchy-pkg-add` (`FLATPAK_COMMAND`), is pinned and scanned always, as the AUR's two
    commands are: the Store installs the `flatpak` package only through `omarchy-pkg-add flatpak` in Omarchy's terminal,
    and only while the catalog pins it and the installed files match. `pinned_recipes` takes it; `check-env` reports a
    finding as `Get Flatpak command omarchy-pkg-add: …`, and refuses when Omarchy's stable mirror has no `flatpak`
    package (`FLATPAK_PACKAGE`). The lock's pins are unchanged (`omarchy-pkg-add` and `omarchy-pkg-missing` were pinned
    through the setups); its comment names the command.
  - `validate`: an "omarchy" object always pins `bin/omarchy-pkg-add` and the `omarchy-pkg-missing` it calls first
    (`FLATPAK_PINS`, the Store's `requiredPins`); without the object, the Store does not offer Get Flatpak….
  - catalog/README.md: Get Flatpak's command among the pins.
  - Tests: `tests/run-in-container.sh --network host`: `Ran 59 tests … OK`, exit 0 (Rules.test_omarchy, Recipes.test_pins
    and Recipes.test_check_env extended); 4 mutants of the change (the command left out of the pins, the validation, the
    scan, the package check) each fail them. `validate: ok`. `check-env` with Omarchy v4.0.4 and the stable mirror's
    package list: nothing about Get Flatpak (`flatpak` 1:1.18.4-2 in [extra]); the same 10 findings as main from this
    session's partial copy of the application-entry facts, unrelated.

- 2026-10-31, the build container on Omarchy's own repository too (branch `claude/build-omarchy-repo` from main 33cd831;
  the owner asked for it while the integrator is away, « Fait les 4 »):
  - Found while Software Update step 3 was reviewed: `build/pacman.conf` left `[omarchy]` out, so grassfield-desktop's
    BUILD-DEPS recorded `[extra]`'s quickshell (0.3.2-1). Omarchy users run `[omarchy]`'s (0.3.2.r7.g2b4501a-1, checked
    on pkgs.omarchy.org on 2026-10-31). The client's compatibility check compares quickshell's whole version (grassfield
    ADR-0033 s3.4), so a published channel would have refused every update that changes a tracked package. Local builds
    on the owner's machine were not affected.
  - `build/pacman.conf`: `[omarchy]` (`https://pkgs.omarchy.org/stable/$arch`) first, as Omarchy 4.0.6's
    `pacman-stable.conf`. Among what Grassfield builds against, it has only quickshell; none of the 137 packages of
    `archlinux:base` is in it.
  - `scripts/build-channel.sh`:
    - trusts `[omarchy]`'s packaging key as an Omarchy machine does: by the fingerprint Omarchy pins
      (`omarchy-update-keyring`, 40DFB630FF42BCFFB047046CF0134EE680CAC571), fetched over HTTPS from keys.openpgp.org and
      used only if the file holds that one key (`pacman-key --add`, `--lsign-key`);
    - after makepkg, checks that each version grassfield-desktop's BUILD-DEPS records is the one pacman installs from
      `build/pacman.conf` (`pacman -Sddp`), and prints it with its repository.
  - `tests/e2e.sh`: two expectations: the key line, and BUILD-DEPS's five lines with quickshell from `[omarchy]`.
  - README: the build package set.
  - Tests:
    - `tests/e2e.sh --grassfield <grassfield at b6fdedf>` on the fix: exit 0, 423 PASS, 0 FAIL. The real PKGBUILD was
      built four times on the new package set; build-channel.sh's BUILD-DEPS check passed each time, since it would have
      stopped the build otherwise.
    - Second run with the two new expectations (2370faa, grassfield at db67a5f's parent b369f16): exit 0, 425 PASS, 0
      FAIL. The build printed the line naming Omarchy's signer by its pinned fingerprint (now worded `[omarchy] signer
      trusted, fingerprint …`, see the gitleaks note below) and BUILD-DEPS
      `qt6-base 6.12.0-3` [extra], `quickshell 0.3.2.r7.g2b4501a-1` [omarchy], `hyprland 0.56.2-4` [extra],
      `aquamarine 0.15.1-1` [extra], `kcoreaddons 6.31.0-1` [extra].
    - gitleaks on the branch: three `generic-api-key` findings, all Omarchy's public signer fingerprint next to the word
      "key" (scripts/build-channel.sh, tests/e2e.sh, this file). They are not secrets: the fingerprint is public, pinned in
      Omarchy's own `omarchy-update-keyring`. Already pushed, so they are listed in a new `.gitleaksignore` (history is
      never rewritten), and the files now say "fpr"/"signer"; gitleaks then: no leaks.
  - The integrator's review of 4ea067a (opus, security and supply-chain): FAIL on one gap; provenance, the key check and the
    gitleaks entries hold. Answered in the next commit:
    - MAJOR: tests/smoke.sh (CI's test job) never trusted [omarchy]'s signer, so quickshell from [omarchy] would have been
      refused. One helper, scripts/omarchy-trust.sh, now does the pinned-fingerprint step for build-channel.sh and
      smoke.sh alike; smoke.sh also checks that quickshell came from [omarchy].
    - Minor: [omarchy] first also wins a virtual dependency it provides. qt6-webengine's ttf-font would have been
      [omarchy]'s 152 MB maplemono-nf-cn: the build installs ttf-dejavu from [extra] first. Mesa answers opengl-driver
      because every depends array names it first. The build prints which packages came from [omarchy], and the e2e
      expects quickshell alone.
    - Minor: the lsign trusts Omarchy's signer for [core] and [extra] too, since pacman has one keyring for every
      repository: a SigLevel can be set per repository, but there is no per-repository keyring. That is the same as an Omarchy machine, in a container thrown away after
      one build or test. It is said in the helper.
    - Nits: a secret key in the answer is refused too (only one primary key, public); `pacman -Sddp` reads /dev/null, not
      the loop's input; the helper removes its temporary folder on every path.
    - Information, from grassfield ADR-0033 s3.4: builds from this set record quickshell 0.3.2.r7.g2b4501a-1 and qt6-base
      6.12.0-3. A machine still ordered like Omarchy 4.0.4, with [omarchy] last (quickshell 0.3.1-1, qt6-base 6.11.2-3),
      has those updates refused by Software Update until Omarchy 4.0.6's migration 1791403252 puts [omarchy] first and
      its next update aligns it. This is expected. The owner's local builds are not affected.
  - The integrator's delta re-review of aec4294: PASS; before the merge, the e2e on aec4294. Run here with grassfield
    main 0f5ad09: exit 0, its summary "47 checks, 0 failure(s)" (426 PASS lines with check-tree's own, 0 FAIL). Among them
    "[omarchy]'s signer trusted by Omarchy's pinned fingerprint", "only quickshell came from [omarchy]" and the BUILD-DEPS
    expectation. The earlier "423" and "425" were the same kind of PASS-line count. CI's two jobs, replayed in containers
    on aec4294: the build rc 0 (check-tree all PASS), and smoke.sh 7 checks, 0 failures, quickshell
    0.3.2.r7.g2b4501a-1 from [omarchy].
  - Next: the integrator's merge.

- 2026-11-04/05 (integrator): first publication and build speed.
  - Live at packages.grassfield.site, unannounced (owner decision of 2026-11-04). Beta snapshots:
    - 20261104T230435Z-1982baefa907: 1.0.0rc2-1;
    - 20261104T234957Z-cd39bd000509: 1.0.0rc3-1 and grassfield-keyring 20261104-1.
    Database and packages verified with gpgv against the owner's key (E4921A382C349308BAA50D2F44C31B5D862EBEFA): Good
    signature. Immutable package headers. stable answers 404 (no release; the stable job skips: "nothing to publish").
  - #17 (fbacfe07): publish.py makes the snapshot folder 0755 (mkdtemp's 0700 broke the upload), test `LocalStoreModes`.
  - #18 (96be0c93, opus security PASS):
    - timings in every build summary;
    - ccache and pacman caches for branch builds only; no cache of any kind in a run that can reach the release job
      (`USE_CACHE`, guarded by tests/test_workflows.py, which fails in CI without PyYAML);
    - zstd -T0 -3 written down;
    - the tag poll every 10 minutes behind `GRASSFIELD_TAG_POLL`, set to `on` 2026-11-05 01:02Z.
    Measured branch builds of v1.0.0-rc3: 24 min 48 s cold (41936088220), 17 min 45 s warm (41939837100). Release
    builds stay about 25-27 min by design.
  - #19 (25102076, opus security PASS):
    - the artifact holds regular files only (upload-artifact follows links);
    - a release-capable build takes only a tag whose commit is HEAD and on grassfield's main;
    - stronger guard tests with mutations.
    Dev run 41946828738: build and test success with the new upload folder. The ancestry step has not run in CI yet (branch
    runs skip it): check its log on the first tag build of main.
  - The poll: a manual run (41948705401) succeeded and started nothing (rc2 and rc3 built and listed). GitHub's scheduler
    throttles this repository: with the old `*/15` cron, scheduled runs came every 4-8 hours, and none came in the 45
    minutes after the variable was set. The integrator starts the build right after tagging; the poll is the fallback.
    An immediate start needs a token secret in grassfield and a tag workflow there (owner step, optional).

## Tests run
- O22 follow-up (`docs/evidence/o22-2026-10-27/`, on f678b7d / db904b8, grassfield 448a381 and 4b7aa31): unit tests 53
  OK; release-build.sh 36/0; install-repro (main deletes one of two keys, this branch both); guard.sh 6/0 (4b7aa31
  refused after makepkg, 448a381 built, the dependency in both sets); smoke.sh 6/0 (the keyring installed as a
  dependency); e2e.sh 44/0; gitleaks clean. On the merge of main 4a49c07 (003c0f5): unit tests 55 OK, release-build.sh
  36/0.
- PR #6's follow-up: `tests/run-in-container.sh --network host`: `Ran 55 tests … OK`, exit 0. The CI check job replayed in
  a throwaway container: docker exit 0 (`validate: ok`; 15832 packages, 51 entries, 1604 AppStream components; `check-env:
  ok`; both channels verified; no temporary GnuPG home left). `pin` on v4.0.4 in a copy of `catalog/`: `nothing changed`,
  exit 0, the lock byte for byte the same, 19 notes.
- Store step 2: `tests/run-in-container.sh --network host`: `Ran 54 tests … OK`, exit 0. The CI check job replayed in a
  throwaway container: docker exit 0 (`validate: ok`; 15831 packages, 51 entries and 1604 AppStream components gathered;
  `check-env: ok`; both channels built, signed with a throwaway key and verified; no temporary GnuPG home left).
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
- Pruning of old snapshots (7 days, `tools/publish.py`) and of packages no snapshot names.
- The guard test's known limits (code review is the control): an obfuscated GITHUB_ENV write, a docker `--cache-from`,
  `rsync --copy-links`, a self-ancestry check.
- The tag poll's real latency depends on GitHub's scheduler (hours here); see the 2026-11-04/05 entry.

## Open questions (owner)
- None for the catalog. The owner's decisions of 2026-10-27 (legal review with the integrator, recorded on grassfield PR
  #25 and in grassfield ADR-0037 e.10; the full list in grassfield's legal dossier) settle the two questions that were
  here:
  - the section names stay as they are (Discover, Create, Work, Play, Develop): a risk the owner accepts;
  - the category names stay the neutral ones;
  - publishers' icons, screenshots and AppStream texts are shown as provided, with their source;
  - the app name "Grassfield Store" and "Get" / "Open" stay, with the macOS command labels.
  Publication still waits for the owner's decision after the M5 legal review (CLAUDE.md).

## Owner steps
- Done (2026-11-04): the deploy key, the protected `publish-stable` and `publish-beta` environments (required reviewer,
  main only) with the signing key and storage secrets, the Worker and its routes. The integrator may tag, approve the
  publish runs and deploy the Worker after the reviews pass (owner delegation of 2026-11-04); announcing stays the owner's.
- Optional: a token secret in grassfield for an immediate build on a tag.

## Next
- The integrator's review of step 3c part 3's half (this branch's PR, Get Flatpak's command pinned), with grassfield's
  3c part 3 PR.
- Store step 4 (the Updates page), one PR in grassfield, with this repository's half when the catalog's contract changes
  (ADR-0037 g).
- The Store's later steps add to the catalog (icons for apps without metadata after the legal review).
