# Grassfield packages

Builds, signs and serves the pacman repository of Grassfield Desktop, in two channels: **stable** and **beta**.

- The desktop itself, its `PKGBUILD` and the Software Update client live in
  [grassfieldhq/grassfield](https://github.com/grassfieldhq/grassfield). The contract between the two repositories
  (channel URLs and layout, file names, release notes, signing key and trust) is that repository's
  `docs/decisions/ADR-0033` (Software Update). Read it before changing anything here.
- This repository holds the infrastructure only: building the packages from a Grassfield tag in a clean environment,
  signing, the `grassfield-keyring` package, `repo-add`, CI and, later, hosting.

## Status
Nothing is published. The repository stays private until the owner decides, after the legal review of milestone M5.
CI produces artifacts only; the publishing step is disabled. `grassfield-keyring` holds no key until the owner provides
the project's signing key (ADR-0033 O11, O20).

## Layout
| Path | What |
|---|---|
| `keyring/` | `grassfield-keyring`: `PKGBUILD`, its install script, and `grassfield.gpg`, `grassfield-trusted`, `grassfield-revoked` (empty until the owner's key), installed in Grassfield's private folder `/usr/share/grassfield/pacman-keyring/` (ADR-0033 b.2) |
| `build/pacman.conf` | the build container's package set: Omarchy's stable mirror, so Hyprland, Qt and KF6 are the versions Omarchy's stable users run (ADR-0033 f) |
| `scripts/build-channel.sh` | one Grassfield tag or commit → makepkg of grassfield's own PKGBUILD → signed packages → a new signed snapshot (database, files, release notes) of each channel it goes to → the pointer |
| `scripts/notes.py` | `grassfield-notes.json` from grassfield's `packaging/release-notes/<VERSION>.{en,fr}.txt` |
| `scripts/check-tree.sh` | the tree against the contract: signatures, names, no `replaces=`, notes, no links |
| `scripts/rollback.sh` | a rollback is a new snapshot with older packages, never the pointer moved back (ADR-0033 h.2, R4) |
| `scripts/view.sh`, `scripts/serve.py` | for tests: the tree as the hosting's edge rule serves it, as files (`file://`) or over HTTP with its redirects |
| `tests/e2e.sh` | the end-to-end exercise with the real packages and grassfield's client, in a throwaway container |
| `tests/smoke.sh` | CI's test job: a fresh machine installs a built tree and the client answers |
| `.github/workflows/` | `build` (on demand: build, test; publish written and disabled), `poll` (every 15 minutes, off until the owner turns it on), `watch-hyprland` (by hand until something is published) |

The tree a build writes, per channel and arch (ADR-0033 g, h.2):

    <channel>/x86_64/<package>.pkg.tar.zst and .sig     immutable names
    <channel>/x86_64/snap/<id>/grassfield.db, .files, grassfield-notes.json, each with .sig
    <channel>/x86_64/pointer                           the current snapshot, written last
    build-<id>.txt                                     ref, commit, versions, Hyprland, the plugin's ABI stamp, pacman -Q

## Commands
Every build and test runs as root inside a throwaway Arch container, never on a real machine (`CLAUDE.md`).

    tests/e2e.sh --grassfield ~/workspace/grassfield [--ref REF]     # builds 1.0.0, 1.0.1 and 1.1.0-beta1 of REF (~1 h)
    docker run --rm -v "$PWD:/packages:ro" -v <grassfield>:/grassfield:ro -v "$PWD/out:/out" \
      archlinux:base@sha256:52dfbd5afb23a220d5ee92dafcb4c788d96c026ed04179890c23adef4c897fa0 \
      /packages/scripts/build-channel.sh --source /grassfield --ref <tag> --tree /out/tree --gnupghome <dir> --key <fpr>

## From the owner, later (none exists; nothing here creates them)
- secret `GRASSFIELD_DEPLOY_KEY`: a read-only deploy key of grassfieldhq/grassfield (O13); then the variable
  `GRASSFIELD_TAG_POLL=on` turns the tag poll on (O14);
- environment `release` (protected, the owner approves each run) with the secrets `GRASSFIELD_SIGNING_KEY`,
  `GRASSFIELD_SIGNING_PASSPHRASE` (O6), `GRASSFIELD_S3_ACCESS_KEY_ID`, `GRASSFIELD_S3_SECRET_ACCESS_KEY` and the variables
  `GRASSFIELD_S3_BUCKET`, `GRASSFIELD_S3_ENDPOINT` (O8);
- the public key and its fingerprint (in `keyring/` here and in grassfield's `packaging/pacman/`), the host name.

## License
MIT, see `LICENSE`. Packaged third-party software keeps its own licenses.
