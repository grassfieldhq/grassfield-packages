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
CI produces artifacts only; the publishing step is disabled.

## License
MIT, see `LICENSE`. Packaged third-party software keeps its own licenses.
