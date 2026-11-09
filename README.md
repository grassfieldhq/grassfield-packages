# Grassfield packages

Builds, signs and serves, in two channels (**stable** and **beta**), the pacman repository of Grassfield Desktop and the
catalog of Grassfield Store.

- The desktop itself, its `PKGBUILD`, the Software Update client and the Store app live in
  [grassfieldhq/grassfield](https://github.com/grassfieldhq/grassfield). Two of its decisions are the contract with this
  repository; read them before changing anything here:
  - `docs/decisions/ADR-0033` (Software Update): channel URLs and layout, file names, release notes, signing key and trust,
    atomic publication;
  - `docs/decisions/ADR-0037` (Grassfield Store): the catalog's format, its signature and the checks the Store makes. It
    extends ADR-0033.
- This repository holds the infrastructure and the editorial data only:
  - building the packages from a Grassfield tag in a clean environment, signing, the `grassfield-keyring` package,
    `repo-add`, CI and, later, hosting;
  - the **Store catalog** Grassfield edits: the Discover selection, the sections, the categories, our short texts in English
    and French, and the icons of apps that ship no metadata (their publishers' icons, with licence and origin recorded; needs
    legal review before any publication). CI validates it and signs it with the repository's key. It changes without a new
    Grassfield release.
- **One publisher per channel.** Package releases and catalog updates share each channel's snapshot pointer, so they go
  through one serialized publishing job per channel: it builds the new snapshot from the current one, never puts an older
  package database back, and writes the pointer only if it has not moved since it read it (ADR-0037 g, ADR-0033 h.2 as
  amended). A catalog update can never move the package database back.
- **Each publishing run publishes the latest state.** GitHub cancels a run still waiting in a concurrency group when a newer
  one queues, and each tag is built once, so a run takes nothing from the event that started it: it publishes the newest
  release built and signed for the channel and the catalog of `main`'s head. A cancelled waiting run loses nothing; a run
  with nothing new writes nothing.

## Layout
| Path | What |
|---|---|
| `catalog/` | the Store catalog's sources: categories, sections, apps, icons, the pinned Omarchy release (`catalog/README.md`) |
| `keyring/` | `grassfield-keyring`: `PKGBUILD`, its install script, and `grassfield.gpg`, `grassfield-trusted`, `grassfield-revoked` (empty; the owner's key since 2026-11-04), installed in Grassfield's private folder `/usr/share/grassfield/pacman-keyring/` (ADR-0033 b.2) |
| `grassfield-sanaga/`, `grassfield-notes/` | the two bundled apps (grassfield ADR-0055), one `PKGBUILD` each, pinned to one commit of the app's `main` (see "Bundled apps" below). Top-level folders beside `keyring/`: they are packages built from other repositories' source, and each folder is exactly what `build-channel.sh` copies and builds |
| `build/pacman.conf` | the build container's package set: Omarchy's own repository first, then its stable mirror, as an Omarchy stable machine has them, so Hyprland, Qt, KF6 and quickshell (from `[omarchy]`) are the versions Omarchy's stable users run (ADR-0033 f); `scripts/omarchy-trust.sh` trusts `[omarchy]`'s signer by Omarchy's pinned fingerprint, for the build and the smoke test; `build-channel.sh` installs a font of `[extra]` first (so `[omarchy]` does not answer qt6-webengine's `ttf-font`), checks that BUILD-DEPS records those versions and prints what came from `[omarchy]` |
| `tools/publish.py` | the one serialized publisher of a channel (ADR-0033 h.2, ADR-0037 g): from the current snapshot, the newest release build and the catalog of `main`'s head, never backwards, immutable names, the pointer written only if it has not moved; ADR-0033 h.2's deliberate rollback (`--rollback-to`). Run by `publish.yml` against the bucket (`S3Store`, through `aws s3api`); the tests and the build's test trees use its local store |
| `tools/catalog.py` | validates the sources, checks them against what they name, builds, signs and verifies the catalog (standard library) |
| `tools/catalog-facts.sh` | gathers those facts in a throwaway Arch container: Omarchy's stable mirror, Arch's AppStream, Flathub |
| `scripts/build-channel.sh` | one Grassfield tag or commit, built once → makepkg of grassfield's own PKGBUILD → signed packages → its **release build** for each channel it goes to (`releases/<channel>/<version>/`: packages, a database of this release alone, release notes, all signed), which the publisher reads → the channel tree made from them by `tools/publish.py`, for CI's artifact and the tests; grassfield-keyring is built once per version (reused only while it is still `keyring/`'s, the whole package); grassfield-sanaga and grassfield-notes are built in the same container before grassfield-desktop (which depends on them) and reused from the tree when signed by the key and built from the very PKGBUILD in git (`app-check.sh`); a release whose grassfield-desktop does not depend on grassfield-keyring is refused (grassfield ADR-0033 O22); throwaway keys only (it refuses to start beside the project's key) |
| `scripts/bump-app.sh`, `scripts/app-check.sh` | `bump-app.sh <app> <commit>` moves an app's pin in one step (`--verify <app>` recomputes it from the network); `app-check.sh` is the reuse rule: a built package stands for a folder's PKGBUILD only if it records that PKGBUILD's SHA-256 |
| `scripts/omarchy-trust.sh` | `[omarchy]`'s package signer trusted in a throwaway container's pacman keyring as an Omarchy machine trusts it: the fingerprint Omarchy pins, the key fetched over HTTPS from keys.openpgp.org and used only if it is that one key alone; one step for `build-channel.sh` and `tests/smoke.sh` |
| `scripts/sign-release.sh` | a tested release build signed with the project's key (the `release` job, disabled), in two steps so the key never meets anything that reads package contents: `prepare` without the key (a package already published used as it is, the keyring compared with `keyring/`, `repo-add`), `sign` with gpg only, on an allowlist of names |
| `scripts/notes.py` | `grassfield-notes.json` from grassfield's `packaging/release-notes/<VERSION>.{en,fr}.txt`, with the channel's earlier releases from the tag's own repository |
| `scripts/check-tree.sh` | the tree against the contract: signatures (`--trusted`: by a key the shipped grassfield-keyring trusts, as a client checks them; `--keyring-src`: that keyring byte for byte `keyring/`'s), every package with the SHA-256 its database records, each snapshot's manifest, a release build holding nothing else, names, no `replaces=`, grassfield-desktop depending on grassfield-keyring, notes, no links |
| `scripts/rollback.sh` | a deliberate rollback (ADR-0033 h.2, R4): the newer release builds withdrawn, so a later run does not put them back, then `tools/publish.py --rollback-to`, a new snapshot, never the pointer moved back |
| `scripts/snapshot.py` | reads a channel's pointer (`{"snapshot": "<id>"}`) for the shell tools |
| `scripts/view.sh`, `scripts/serve.py` | for tests: the tree as the hosting's edge rule serves it, as files (`file://`) or over HTTP with its redirects |
| `tests/` | unit tests of the catalog and the publisher (`tests/run-in-container.sh` runs them where throwaway keys may be made); `e2e.sh`, the end-to-end exercise with the real packages and grassfield's client; `smoke.sh`, CI's test job; `release-build.sh`, the release build's pieces with small fake packages |
| `.github/workflows/catalog.yml` | CI: tests, checks, a catalog signed with a throwaway key as an artifact |
| `.github/workflows/build.yml` | on demand, a tag or a pkgrel rebuild of it: build with a throwaway key, test; `release`, written and disabled, per channel in the publisher's environments: a tag's tested release build prepared without the key, signed with it (gpg only, no network), checked as a client checks it without the key, and kept where the publisher reads it |
| `.github/workflows/publish.yml` | the publishing job, one per channel, serialized, written and disabled (`if: false`, no secret): on a push to `main` or when a build completes, it publishes the latest state |
| `edge/` | the Cloudflare Worker of `packages.grassfield.site` (ADR-0033 h.5): the fixed names answer the same 302 as `scripts/serve.py` from `<channel>/x86_64/pointer`, everything else is the bucket's object with the cache headers of h.5; `worker.test.mjs` checks it against `serve.py`; deployed by hand (`docs/first-run.md`) |
| `docs/first-run.md` | the first publication, step by step |
| `.github/workflows/poll.yml`, `watch-hyprland.yml` | the tag poll (every 15 minutes, off until the owner turns it on); the toolkit watch, daily (ADR-0033 f, ADR-0041 step 2a): compares the published build's Hyprland ABI stamp, quickshell and qt6-base with Omarchy's stable and rc channels, starts a pkgrel rebuild when stable moved (publication still waits for approval) and opens an issue when only rc moved |

## Bundled apps
Grassfield's session ships two apps of its own: Sanaga (the default browser) and Grassfield Notes. Each is a package of
this repository, built from one pinned commit of its own repository and signed like the desktop; `grassfield-desktop`
depends on them (grassfield ADR-0055).

| Folder | Package | Provides | Installs |
|---|---|---|---|
| `grassfield-sanaga/` | `grassfield-sanaga` | `sanaga` (and `conflicts=(sanaga)`) | `/usr/bin/sanaga`, `sanaga.desktop`, hicolor icons, metainfo |
| `grassfield-notes/` | `grassfield-notes` | nothing | `/usr/bin/grassfield-notes`, `grassfield-notes.desktop`, hicolor icons |

- **The name.** The channel holds only `grassfield-*` packages, none with `replaces=` (ADR-0033 b.6, unchanged), so the
  browser's package is `grassfield-sanaga` and it provides `sanaga`, the name the desktop depends on.
  **A machine with a self-built `sanaga` package must remove it once** (`sudo pacman -Rns sanaga`), before the first update
  that brings `grassfield-sanaga`. The conflict is deliberate: without it both packages would own `/usr/bin/sanaga`.
- **The source** is GitHub's archive tarball of the pinned commit with its SHA-256 in `sha256sums`, never a git source
  (makepkg checks no checksum of a git source, it writes `SKIP`), a tag or a branch. If GitHub ever changed the bytes of an
  archive, the build would fail on the checksum rather than package other bytes; `bump-app.sh --verify` shows it.
- **The build**: `cargo fetch --locked` in `prepare()` (the only network step; crates are checked against `Cargo.lock`),
  an offline `cargo build --frozen --release`, `check()` running `cargo test --frozen --release` (headless), then
  `package()`. `makedepends=(rust)`; the run-time libraries of eframe (wayland, libxkbcommon, libglvnd) are named in
  `depends` because they are opened with dlopen and show in no `NEEDED` list.
- **The version**: `pkgver` = Cargo.toml's version + `.r<commits up to the pinned commit>` + `.g<first 7 hex of the commit>`,
  for example `0.4.0.r79.ga9e0e56` (Arch's form for a pinned non-tag commit; the count keeps versions ordered along `main`,
  and the publisher refuses a package older than the published one). `pkgrel` is 1 for a new commit.
- **Bumping** is one command, and the result is reviewed. Never edit the pin by hand:

      scripts/bump-app.sh grassfield-sanaga <full 40-hex commit of sanaga's main>
      scripts/bump-app.sh grassfield-notes  <full 40-hex commit of grassfield-notes' main>

  It refuses a commit that is not on the app's `main` or not a descendant of the pinned one, then rewrites `_commit`, `_rev`,
  `_cargover`, `sha256sums` and `pkgrel` together from the app's history and archive. The pull request names the new SHA
  (and why: the security fixes, the version) and is reviewed: the reviewer runs `scripts/bump-app.sh --verify <app>` and gets
  the same version, count and checksum, and reads the app's diff between the two commits. Any other edit of a
  `PKGBUILD` is a new `pkgrel`.
- **Reuse.** `build-channel.sh` builds both in the container it builds the desktop in, before it (the desktop's `makepkg -s`
  needs them installed). A package of the same name already in the tree is used again, with its signature, only if the
  key signed it and `scripts/app-check.sh` finds it built from this very `PKGBUILD` (`.BUILDINFO` records its SHA-256, and the
  `PKGBUILD` holds the commit and the checksum); a changed `PKGBUILD` without a new `pkgrel` stops the build. The release job
  already uses a package published under the same name as it is.
- **Time.** A release build compiles both from scratch (no cache on a run that can reach the release job,
  `docs/build-caches.md`): about 10-15 minutes more for Sanaga and 5-8 for Notes on the runner, on top of the 25-27 minutes
  of the desktop (estimates; the first CI run measures them).

## Status
Going live, unannounced, by the owner's decision of 2026-11-04: the repository is public and its packages are served at
https://packages.grassfield.site (Cloudflare R2 behind the Worker of `edge/`). The legal review stays mandatory before any
announcement. The release job and `publish.yml` are enabled in the protected environments `publish-stable` and
`publish-beta` (the owner approves each run; `main` only); the tag poll stays off. `grassfield-keyring` holds the owner's
public key (fingerprint `E4921A382C349308BAA50D2F44C31B5D862EBEFA`). Nothing is published until the owner starts the first
run: `docs/first-run.md`.

The tree a build writes (ADR-0033 g, h.2; ADR-0037 g):

    releases/<channel>/<version>/                      the release build the channel's publisher reads, never under a pointer
    withdrawn/<channel>/<version>/                     release builds a rollback withdrew (the publisher never reads them)
    <channel>/x86_64/<package>.pkg.tar.zst and .sig     immutable names
    <channel>/x86_64/snap/<id>/grassfield.db, .files, grassfield-notes.json, each with .sig, manifest.json, and the
                                                       other files the snapshot kept (the catalog)
    <channel>/x86_64/pointer                           {"snapshot": "<id>"}, written last, only if it has not moved
    build-<id>.txt                                     ref, commit, versions, Hyprland, the plugin's ABI stamp, pacman -Q

## Commands
Every build and test runs as root inside a throwaway Arch container, never on a real machine (`CLAUDE.md`).

    tests/run-in-container.sh                                        # unit tests: the catalog and the publisher
    tests/e2e.sh --grassfield ~/workspace/grassfield [--ref REF]     # builds 1.0.0, 1.0.1, 1.0.1 pkgrel+1, 1.1.0-beta1 (~1 h)
    tests/release-build.sh                                           # the release build's pieces, fake packages (~2 min)
    docker run --rm -v "$PWD:/packages:ro" -v <grassfield>:/grassfield:ro -v "$PWD/out:/out" \
      archlinux:base@sha256:52dfbd5afb23a220d5ee92dafcb4c788d96c026ed04179890c23adef4c897fa0 \
      /packages/scripts/build-channel.sh --source /grassfield --ref <tag> --tree /out/tree --gnupghome <dir> --key <fpr>

## Set by the owner (2026-11-03/04; nothing here creates them)
- secret `GRASSFIELD_DEPLOY_KEY`: a read-only deploy key of grassfieldhq/grassfield (O13); then the variable
  `GRASSFIELD_TAG_POLL=on` turns the tag poll on (O14);
- the publisher's protected environments `publish-stable` and `publish-beta` (the owner approves each run), which the
  build workflow's `release` job uses too, with the secrets `GRASSFIELD_SIGNING_KEY`, `GRASSFIELD_SIGNING_PASSPHRASE`
  (O6), `GRASSFIELD_S3_ACCESS_KEY_ID`, `GRASSFIELD_S3_SECRET_ACCESS_KEY` and the variables `GRASSFIELD_S3_BUCKET`,
  `GRASSFIELD_S3_ENDPOINT` (O8);
- the public key and its fingerprint (in `keyring/` here and in grassfield's `packaging/pacman/`), the host name.

## License
MIT, see `LICENSE`. Packaged third-party software keeps its own licenses; app icons in the catalog keep their owners' terms,
recorded beside each one.
