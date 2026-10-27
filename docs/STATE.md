# Grassfield packages — Current State
Last updated: 2026-10-27

## Done
- Repository created (private) with README, LICENSE (MIT), CLAUDE.md and this file.

## Next
- Wait for ADR-0033 (Software Update) to pass review in grassfieldhq/grassfield; it fixes the contract this repository
  implements.
- Then: build from a Grassfield tag in a clean Arch container (with the Hyprland of Omarchy's stable channel, see
  grassfield ADR-0009), signing, `grassfield-keyring`, `repo-add` per channel, CI producing the channel repository as an
  artifact. No publication.
