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
| `keyring/` | `grassfield-keyring`: `PKGBUILD`, its install script, and `grassfield.gpg`, `grassfield-trusted`, `grassfield-revoked` (empty until the owner's key), installed in Grassfield's private folder `/usr/share/grassfield/pacman-keyring/` (ADR-0033 b.2) |
| `build/pacman.conf` | the build container's package set: Omarchy's stable mirror, so Hyprland, Qt and KF6 are the versions Omarchy's stable users run (ADR-0033 f) |
| `tools/publish.py` | the one serialized publisher of a channel (ADR-0033 h.2, ADR-0037 g): from the current snapshot, the newest release build and the catalog of `main`'s head, never backwards, immutable names, the pointer written only if it has not moved; ADR-0033 h.2's deliberate rollback (`--rollback-to`). Written and disabled in CI (the bucket's backend waits for the host); the tests and the build's test trees use its local store |
| `tools/catalog.py` | validates the sources, checks them against what they name, builds, signs and verifies the catalog (standard library) |
| `tools/catalog-facts.sh` | gathers those facts in a throwaway Arch container: Omarchy's stable mirror, Arch's AppStream, Flathub |
| `scripts/build-channel.sh` | one Grassfield tag or commit, built once → makepkg of grassfield's own PKGBUILD → signed packages → its **release build** for each channel it goes to (`releases/<channel>/<version>/`: packages, a database of this release alone, release notes, all signed), which the publisher reads → the channel tree made from them by `tools/publish.py`, for CI's artifact and the tests; grassfield-keyring is built once per version; throwaway keys only (it refuses to start beside the project's key) |
| `scripts/sign-release.sh` | a tested release build signed with the project's key (the `release` job, disabled), in a container that runs no build; a package already published is used as it is |
| `scripts/notes.py` | `grassfield-notes.json` from grassfield's `packaging/release-notes/<VERSION>.{en,fr}.txt`, with the channel's earlier releases from the tag's own repository |
| `scripts/check-tree.sh` | the tree against the contract: signatures (`--trusted`: by a key the shipped grassfield-keyring trusts, as a client checks them), every package with the SHA-256 its database records, each snapshot's manifest, names, no `replaces=`, notes, no links |
| `scripts/rollback.sh` | a deliberate rollback (ADR-0033 h.2, R4): the newer release builds withdrawn, so a later run does not put them back, then `tools/publish.py --rollback-to`, a new snapshot, never the pointer moved back |
| `scripts/snapshot.py` | reads a channel's pointer (`{"snapshot": "<id>"}`) for the shell tools |
| `scripts/view.sh`, `scripts/serve.py` | for tests: the tree as the hosting's edge rule serves it, as files (`file://`) or over HTTP with its redirects |
| `tests/` | unit tests of the catalog and the publisher (`tests/run-in-container.sh` runs them where throwaway keys may be made); `e2e.sh`, the end-to-end exercise with the real packages and grassfield's client; `smoke.sh`, CI's test job; `release-build.sh`, the release build's pieces with small fake packages |
| `.github/workflows/catalog.yml` | CI: tests, checks, a catalog signed with a throwaway key as an artifact |
| `.github/workflows/build.yml` | on demand, a tag or a pkgrel rebuild of it: build with a throwaway key, test; `release`, written and disabled, per channel in the publisher's environments: a tag's tested release builds signed with the project's key, checked as a client checks them, and kept where the publisher reads them |
| `.github/workflows/publish.yml` | the publishing job, one per channel, serialized, written and disabled (`if: false`, no secret): on a push to `main` or when a build completes, it publishes the latest state |
| `.github/workflows/poll.yml`, `watch-hyprland.yml` | the tag poll (every 15 minutes, off until the owner turns it on); the Hyprland watch (by hand until something is published) |

## Status
Nothing is published. The repository stays private until the owner decides, after the legal review of milestone M5.
CI produces artifacts only; the publishing workflow and the release job are disabled. `grassfield-keyring` holds no key
until the owner provides the project's signing key (ADR-0033 O11, O20).

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

## From the owner, later (none exists; nothing here creates them)
- secret `GRASSFIELD_DEPLOY_KEY`: a read-only deploy key of grassfieldhq/grassfield (O13); then the variable
  `GRASSFIELD_TAG_POLL=on` turns the tag poll on (O14);
- the publisher's protected environments `publish-stable` and `publish-beta` (the owner approves each run), which the
  build workflow's `release` job uses too, with the secrets `GRASSFIELD_SIGNING_KEY`, `GRASSFIELD_SIGNING_PASSPHRASE`
  (O6), `GRASSFIELD_S3_ACCESS_KEY_ID`, `GRASSFIELD_S3_SECRET_ACCESS_KEY` and the variables `GRASSFIELD_S3_BUCKET`,
  `GRASSFIELD_S3_ENDPOINT` (O8);
- the public key and its fingerprint (in `keyring/` here and in grassfield's `packaging/pacman/`), the host name;
- the bucket's backend of `tools/publish.py`, with the host.

## License
MIT, see `LICENSE`. Packaged third-party software keeps its own licenses; app icons in the catalog keep their owners' terms,
recorded beside each one.
