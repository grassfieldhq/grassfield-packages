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
| `scripts/build-channel.sh` | one Grassfield tag or commit, built once → makepkg of grassfield's own PKGBUILD → signed packages → its **release build** for each channel it goes to (`releases/<channel>/<version>/`: packages, a database of this release alone, release notes, all signed), which the publisher reads → the channel tree made from them by `tools/publish.py`, for CI's artifact and the tests; grassfield-keyring is built once per version (reused only while it is still `keyring/`'s, the whole package); grassfield-sanaga and grassfield-notes come from `--apps`, built beforehand in a container each by `build-app.sh`, checked by `app-check.sh`, and reused from the tree when signed by the key and built from the very PKGBUILD in git; a release whose grassfield-desktop does not depend on grassfield-keyring is refused (grassfield ADR-0033 O22); throwaway keys only (it refuses to start beside the project's key) |
| `scripts/bump-app.sh`, `scripts/app-check.sh` | `bump-app.sh <app> <commit>` moves an app's pin in one step (`--verify <app>` recomputes it from the network); `pin-check.sh` refuses an unpinned PKGBUILD; `build-app.sh` builds one app in its own container; `app-repack.sh` (with `app-lib.sh`) rebuilds each package canonically in a container with no network; `app-check.sh`, `app-ingest.sh` and `release-apps-check.sh` are the second check and the reuse rule between that container and the one that signs |
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
- **The source** is GitHub's archive tarball of the pinned commit with its SHA-256 in `sha256sums`, never a tag or a
  branch. makepkg can also checksum a git source pinned by `#commit=` (the SHA-256 of `git archive`), but that needs a clone
  with its history and those bytes depend on the git version and `.gitattributes`; the archive is one file fetched over HTTPS and
  checked before anything is extracted. The cost: it relies on GitHub keeping an archive's bytes stable. If it ever changed
  them, the build would fail on the checksum rather than package other bytes, and `bump-app.sh --verify` shows it.
  `scripts/pin-check.sh` refuses anything else in a `PKGBUILD`: a second source, `source_<arch>` or `sha256sums_<arch>`
  arrays, `SKIP`, another checksum algorithm, `install=` or `replaces=`.
- **The build, in a container of its own.** The apps run third-party code (800+ crates' build scripts and proc-macros, the
  tests, the binaries `package()` runs). `scripts/build-app.sh` builds each app in a throwaway container with no sudoers
  entry: the dependencies are installed there as root first, then `makepkg` (without `-s`) runs as an unprivileged user in a
  fresh HOME with a scrubbed environment, after `pin-check.sh` and `bump-app.sh --verify`. Only the `.pkg.tar.zst` leaves.
  It shares no user, HOME, SRCDEST or sudoers line with the container that builds `grassfield-desktop`, so a crate cannot
  reach the build the project's key signs (review of PR #22). The network stays on in that container (`pacman`, the source
  and `cargo fetch` need it, and one container cannot cut it for cargo alone): `--frozen` keeps cargo offline, but it is not
  a barrier for a build script or a test.
  `cargo fetch --locked` in `prepare()` (crates are checked against `Cargo.lock`), an offline `cargo build --frozen
  --release`, `check()` running `cargo test --frozen --release` (headless), then `package()`, which also writes
  `THIRD-PARTY-LICENSES.txt` (every linked crate, its version and licence expression, from `cargo tree`) and the licence
  texts of the font crates under `/usr/share/licenses/<package>/`. The legal review of those licences is the owner's. `makedepends=(rust)`; the run-time libraries of eframe (wayland, libxkbcommon, libglvnd) are named in
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
- **The package is made canonical, not predicted.** The file an app container wrote is untrusted (build code could have
  written it), and every parser of ours differs from libarchive's somewhere: Python's `tarfile` stops silently at a header
  libarchive accepts, a second `.PKGINFO` member is read by one reader and not by repo-add, a SIGPIPE inverts a `grep`. So
  `scripts/app-repack.sh` runs in a third container, with no network and only this repository, the package (read-only) and
  an output folder:
  0. which format is parsed: zstd alone decompresses the file to a plain one (under a size cap) and that must BE a tar, a valid
     checksum on its first 512-byte header and `ustar` at offset 257 (libarchive reads whatever format bids highest: a cpio, zip or
     7-Zip file, or a compressed one, named `.pkg.tar.zst` must never reach it); GNU tar must list the same members;
  1. `bsdtar -tf` lists the members: no path twice (`.PKGINFO` included), every path the app's own
     (`scripts/app-lib.sh`: `usr/bin/<its binary>` alone, its `.desktop`, its hicolor icons, its metainfo, its licences
     folder; no `.INSTALL`, no hook, no other binary, no `usr/share/doc`), every segment of only `[A-Za-z0-9._@+-]` (no space,
     control byte, newline or invalid UTF-8: libalpm writes a name raw into its database, one per line), every owner and mode
     as libarchive prints them;
  2. bsdtar extracts it, never `-P`, into an empty folder, with `-p` first and then `--no-xattrs --no-acls --no-fflags` (`-p`
     after them switches them back on): nothing in the archive can put an attribute, a capability (pacman restores
     `security.capability` with no install script), an ACL or a flag on the tree;
  3. the tree is checked on the filesystem itself: only regular files and folders, no setuid, setgid or sticky bit, no group
     or world write, `getfattr -R -d -m -` empty, only the allowed paths, one `.PKGINFO`;
  4. `.PKGINFO` is **generated** from `makepkg --printsrcinfo` of our own PKGBUILD (name, version, arch, description, url,
     licence, depends, optdepends, provides, conflicts) with the measured size and the build date; the original is only
     compared, and any difference, a control byte or invalid UTF-8 refuses the package (so an escape sequence in a licence
     line never reaches repo-add, the signed database or a user's terminal). `.BUILDINFO` is regenerated with the fields
     `app-check.sh` needs, the original having to be clean text built from this PKGBUILD. Then the package is rebuilt as
     makepkg's `create_package` does: folders 0755, files 0644 (the binary 0755), mtimes the build date, `.MTREE`
     regenerated by `bsdtar --format=mtree` with makepkg's options, makepkg's file order, the owner set at creation
     (`--uid 0 --gid 0 --uname root --gname root`, nothing chowns), zstd on one thread (equal input gives equal bytes: repacking
     twice, or repacking the result, is byte-identical within one image);
  5. proof: the result is extracted again with xattrs, ACLs and flags enabled, no attribute appears, the tree is the one
     checked, the listing is all root:root, and `app-check.sh` passes it.
  The container starts as root and does only this as root: copy the file in, drop every privilege and capability (`setpriv`:
  uid and gid 65534, no groups, no capabilities, `no_new_privs`), and install the one result file into `--out`. Everything that
  parses the untrusted file (zstd, bsdtar, find, getfattr, makepkg) runs unprivileged, in a container with no network. It
  prints the libarchive version it used. **That libarchive and zstd are the ones in the pinned image** (`IMAGE` in
  `.github/workflows/build.yml`, with the same digest in `tests/run-in-container.sh`, `tests/release-build.sh`,
  `tests/e2e.sh`, `catalog.yml`, `publish.yml`): with no network the container cannot update them, so the digest must be refreshed when
  libarchive or zstd get a security fix. No job does that today: it is the integrator's step (bump the digest in those places
  after reading Arch's security tracker for libarchive and zstd, and check the image's `bsdtar --version`, printed at the
  top of the repack step's log); a scheduled check of the image's age or of the tracker would be the automation, and is not
  built.
  A second pass follows where the package is signed: `scripts/app-reverify.sh`, in the desktop's container (the same image), repacks
  the repacked file again and requires it to be identical byte for byte (the repack is deterministic, so a canonical package is
  its own fixed point), so the signed file does not depend on the repack container alone. It is a second pass of the same script with the same
  libarchive, **not an independent parser**: it catches tampering and logic slips, not an exploit that works twice. After each
  unprivileged stage every process of uid 65534 is killed before root reads the output; step 0 also asks libarchive itself
  (`bsdtar -tvvf`: an uncompressed POSIX ustar or pax tar, because libarchive decides on decompression before the format) and
  requires GNU tar to read the file with exit status 0; a zstd failure is an error.
  Only that repacked file goes on: `build-channel.sh --apps DIR` takes it through `scripts/app-ingest.sh` and `scripts/app-check.sh`
  (a second check: pinned PKGBUILD, the same paths, no path or `.PKGINFO`, `.BUILDINFO` or `.MTREE` member twice, root owner and
  plain modes, one line for each single-valued `.PKGINFO` key, the PKGBUILD's own dependency lines, a `.BUILDINFO` recording
  the SHA-256 of this very `PKGBUILD`), signs it and installs it with `--noscriptlet`, so no scriptlet runs. There is no
  parser of our own left in the path (the Python reader and the stream scan were removed): `sign-release.sh prepare` only
  sees packages that went through the repack, and runs the same bsdtar-based `app-check.sh`. **libalpm hooks still run**, as root,
  over the app's data, in the desktop's container and on a client. With the paths above, the stock hooks that can match are
  only these: `gtk-update-icon-cache` (`usr/share/icons/*/`, writes `icon-theme.cache` for the hicolor folder) and
  `update-desktop-database` (`usr/share/applications/*.desktop`, writes `mimeinfo.cache` from the `MimeType=` lines). Both are
  stock Arch hooks that every desktop application triggers, parse the app's PNG, SVG and `.desktop` data with their own
  parsers and write only their caches; accepted. No path of the allowlist matches the hooks for MIME packages, fonts, schemas,
  AppStream catalogs (`usr/share/swcatalog`, not `usr/share/metainfo`), systemd, udev, depmod or ldconfig, and the system-wide
  hooks that fire for every package (`Target = *`, such as Omarchy's update guard) never read a package's contents.
- **Reuse.** A package of the same name already in the tree is used again, with its signature, only if the key signed it and
  `app-check.sh` finds it built from this very `PKGBUILD`; a changed `PKGBUILD` without a new `pkgrel` stops the build, and so
  does `sign-release.sh prepare`: `release-apps-check.sh` runs `app-check.sh` on every package of the release whose
  `.PKGINFO` names an app, so the published package of the same name that replaces a new build cannot hide a changed
  `PKGBUILD`, and it refuses a release whose `grassfield-desktop` depends on an app the release does not hold (publish.py would
  otherwise drop the app from the channel and every client's `-Syu` would fail). `--no-apps` exists for the end-to-end test of
  older refs only.
- **CI** runs `bump-app.sh --verify` for both apps (the pin is on the app's `main`, the checksum is GitHub's) in the check
  job and again in each app's container.
- **Time.** A release build compiles both from scratch, in their own containers before the desktop's (no cache on a run that can reach the release job,
  `docs/build-caches.md`): estimated at 15-25 minutes more for Sanaga (WebKitGTK bindings, thin LTO) and 10-15 for Notes on the 4-vCPU
  runner, on top of the 25-27 minutes of the desktop (measured here: Notes' release build and its 43 tests took about 15
  minutes on a laptop sharing its cores with another build; the first CI run gives the real figures).

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
