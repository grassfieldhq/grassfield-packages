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

## Status
Nothing is published. The repository stays private until the owner decides, after the legal review of milestone M5.
CI produces artifacts only; the publishing step is disabled.

## License
MIT, see `LICENSE`. Packaged third-party software keeps its own licenses; app icons in the catalog keep their owners' terms,
recorded beside each one.
