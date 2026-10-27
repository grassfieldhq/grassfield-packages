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

## Tests run
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

## Next
- The integrator's review of the step-1 PR (opus for the signature, the verification and CI).
- ADR-0033's half of this repository (its own step): building from a Grassfield tag in a clean Arch container, signing,
  `grassfield-keyring`, `repo-add` per channel, CI producing the channel repository as an artifact; publish.py's release
  folders are what that build leaves. No publication.
- The Store's later steps add to the catalog (more sections, icons for apps without metadata after the legal review).
