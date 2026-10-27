# Grassfield packages — Current State
Last updated: 2026-10-27

## Done
- Repository created (private) with README, LICENSE (MIT), CLAUDE.md and this file.
- 2026-10-27 (cloud session, branch claude/pensive-thompson-fhk5um, owner brief "Grassfield Store", step 0, docs only): the
  repository's second role, the Store catalog Grassfield edits, added to README.md and CLAUDE.md. Its contract is grassfield
  ADR-0037 (Proposed, in the step-0 PR of grassfield): `grassfield-catalog.v1.json` + `.sig` + `catalog/<sha256>.png` in each
  channel's snapshot beside the repository, signed with the repository's key, verified by the Store like the release notes
  (ADR-0033 d.8). No code here before the opus PASS of ADR-0037.

## Tests run
- None (docs only).

## Next
- Wait for ADR-0033 (Software Update) and ADR-0037 (Store) to pass review in grassfieldhq/grassfield; they fix the
  contracts this repository implements.
- Then (ADR-0033): build from a Grassfield tag in a clean Arch container (with the Hyprland of Omarchy's stable channel, see
  grassfield ADR-0009), signing, `grassfield-keyring`, `repo-add` per channel, CI producing the channel repository as an
  artifact. No publication.
- Then (ADR-0037 step 1): `catalog/` sources, the build and validation tool (standard-library Python), a CI job producing the
  signed catalog with a throwaway key, publication disabled.
