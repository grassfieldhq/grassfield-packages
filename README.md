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
| `tools/catalog.py` | validates the sources, checks them against what they name, builds, signs and verifies the catalog (standard library) |
| `tools/catalog-facts.sh` | gathers those facts in a throwaway Arch container: Omarchy's stable mirror, Arch's AppStream, Flathub |
| `tools/publish.py` | the serialized publisher of a channel, written and disabled (the bucket's backend waits for the host) |
| `tests/` | unit tests; `tests/run-in-container.sh` runs them where throwaway keys may be made |
| `.github/workflows/catalog.yml` | CI: tests, checks, a catalog signed with a throwaway key as an artifact; publishing disabled |

## Status
Nothing is published. The repository stays private until the owner decides, after the legal review of milestone M5.
CI produces artifacts only; the publishing step is disabled.

## License
MIT, see `LICENSE`. Packaged third-party software keeps its own licenses; app icons in the catalog keep their owners' terms,
recorded beside each one.
